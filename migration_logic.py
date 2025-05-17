import gitlab
import os
import subprocess
import shutil
import time
from dotenv import load_dotenv

load_dotenv()

# --- Configuration from .env ---
OLD_GITLAB_URL = os.getenv('OLD_GITLAB_URL')
OLD_GITLAB_TOKEN = os.getenv('OLD_GITLAB_TOKEN')
OLD_GITLAB_SSH_HOST = os.getenv('OLD_GITLAB_SSH_HOST')
OLD_GITLAB_SSH_PORT = os.getenv('OLD_GITLAB_SSH_PORT')

NEW_GITLAB_URL = os.getenv('NEW_GITLAB_URL')
NEW_GITLAB_TOKEN = os.getenv('NEW_GITLAB_TOKEN')
NEW_GITLAB_SSH_HOST = os.getenv('NEW_GITLAB_SSH_HOST')
NEW_GITLAB_SSH_PORT = os.getenv('NEW_GITLAB_SSH_PORT')

# This is the default if not specified, script will create top-level groups.
# If you want all migrated groups to go under ONE specific pre-existing group on the new instance,
# set this ID in the initial call to migrate_groups_recursive_py in run_full_migration().
TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = os.getenv('TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL', None)
if TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL:
    try:
        TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = int(TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL)
    except ValueError:
        print(f"WARNING: TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL ('{TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL}') is not a valid integer. Will create groups at top level.")
        TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = None


MIGRATION_TEMP_DIR = "./gitlab_migration_temp_python_v3"

# --- Global state ---
migration_status_log = []
OLD_TO_NEW_GROUP_ID_MAP = {}  # old_id -> new_id
CREATED_PATHS_IN_NEW_NAMESPACE = {} # key: new_namespace_id (or "user_namespace"), value: set of project_paths

gl_old = None
gl_new = None

def log_status(message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    full_message = f"[{timestamp}] {message}"
    print(full_message) # For pm2 console logs
    migration_status_log.append(full_message) # For web UI

def initialize_gitlab_clients():
    global gl_old, gl_new
    log_status("--- Initializing GitLab Clients ---")
    try:
        log_status(f"Old GitLab Client: URL={OLD_GITLAB_URL}")
        gl_old = gitlab.Gitlab(OLD_GITLAB_URL, private_token=OLD_GITLAB_TOKEN, timeout=30, keep_base_url=True)
        gl_old.auth()
        log_status("Old GitLab client authenticated successfully.")
    except Exception as e:
        log_status(f"FATAL ERROR: Failed to initialize/authenticate old GitLab client: {e}")
        gl_old = None
        raise # Re-raise to stop the process

    try:
        log_status(f"New GitLab Client: URL={NEW_GITLAB_URL}")
        gl_new = gitlab.Gitlab(NEW_GITLAB_URL, private_token=NEW_GITLAB_TOKEN, timeout=30, keep_base_url=True)
        gl_new.auth()
        log_status("New GitLab client authenticated successfully.")
    except Exception as e:
        log_status(f"FATAL ERROR: Failed to initialize/authenticate new GitLab client: {e}")
        gl_new = None
        raise # Re-raise to stop the process
    log_status("--- GitLab Clients Initialized ---")


def get_full_group_object_old_gl(group_id_or_lazy_obj):
    """Helper to ensure we have a full group object from the old GitLab instance."""
    if not gl_old: return None
    try:
        group_id = group_id_or_lazy_obj.id if hasattr(group_id_or_lazy_obj, 'id') else group_id_or_lazy_obj
        return gl_old.groups.get(group_id)
    except Exception as e:
        log_status(f"ERROR: Could not get full group object for old_id {group_id}: {e}")
        return None

def create_or_find_group_on_new(old_group_obj_full, new_parent_id_for_creation=None):
    global CREATED_PATHS_IN_NEW_NAMESPACE # To track paths for projects
    
    name = old_group_obj_full.name
    path_slug = old_group_obj_full.path
    visibility = old_group_obj_full.visibility
    description = old_group_obj_full.description or ""

    log_status(f"Attempting to create/find group '{name}' (Path: {path_slug}) on new instance.")
    if new_parent_id_for_creation:
        log_status(f"  Targeting new parent group ID: {new_parent_id_for_creation}")

    # Construct full path for checking existence (GitLab paths are unique within their parent)
    # This checking logic is complex because `search` is not exact for full_path.
    # We list candidates and then filter.
    try:
        candidate_groups = []
        if new_parent_id_for_creation:
            try:
                parent_group_new = gl_new.groups.get(new_parent_id_for_creation)
                # List subgroups and filter by path
                # subgroups.list() does not support 'search' param directly in all python-gitlab versions easily.
                # Iterating is more reliable for exact path match.
                all_subgroups = parent_group_new.subgroups.list(all=True)
                candidate_groups = [sg for sg in all_subgroups if sg.path == path_slug]
            except gitlab.exceptions.GitlabGetError:
                log_status(f"ERROR: New parent group ID {new_parent_id_for_creation} not found. Cannot create subgroup '{name}'.")
                return None
        else: # Top-level group
            candidate_groups = gl_new.groups.list(search=path_slug, all=True)
            candidate_groups = [g for g in candidate_groups if g.path == path_slug and g.parent_id is None] # Ensure it's really top-level and path matches

        if candidate_groups:
            existing_group = gl_new.groups.get(candidate_groups[0].id) # Get full object
            log_status(f"Group '{existing_group.name}' (Path: {existing_group.path}) already exists with NEW ID {existing_group.id}. Using it.")
            return existing_group

    except Exception as e_check:
        log_status(f"Warning: Error during pre-check for group '{name}': {e_check}. Proceeding with creation attempt.")

    # If not found, attempt to create
    payload = {
        'name': name,
        'path': path_slug,
        'visibility': visibility,
        'description': description
    }
    if new_parent_id_for_creation:
        payload['parent_id'] = new_parent_id_for_creation
    
    try:
        log_status(f"Creating group with payload: {payload}")
        new_group = gl_new.groups.create(payload)
        log_status(f"Successfully created group '{new_group.name}' with NEW ID {new_group.id}.")
        return new_group # This is a full object
    except gitlab.exceptions.GitlabCreateError as e:
        log_status(f"ERROR: Failed to create group '{name}' (Path: {path_slug}). API Message: {e.error_message}. Full Response: {e.response_body}")
        # Attempt to fetch again if error was "already taken" as a fallback
        if "has already been taken" in str(e.error_message).lower() or "path already exists" in str(e.error_message).lower():
             log_status(f"  Retrying find for group '{path_slug}' after 'already taken' error.")
             # Re-attempt find logic
             try:
                if new_parent_id_for_creation:
                    parent_group_new = gl_new.groups.get(new_parent_id_for_creation)
                    all_subgroups = parent_group_new.subgroups.list(all=True)
                    found_groups = [sg for sg in all_subgroups if sg.path == path_slug]
                else:
                    all_groups = gl_new.groups.list(all=True)
                    found_groups = [g for g in all_groups if g.path == path_slug and g.parent_id is None]
                
                if found_groups:
                    log_status(f"Found existing group '{found_groups[0].name}' with ID {found_groups[0].id} on retry.")
                    return gl_new.groups.get(found_groups[0].id)
             except Exception as e_retry_find:
                 log_status(f"  Retry find also failed: {e_retry_find}")
        return None
    except Exception as e_unexp:
        log_status(f"UNEXPECTED ERROR creating group '{name}': {e_unexp}")
        return None


def migrate_groups_recursive_py(old_parent_group_id=None, new_parent_id_for_subgroup_creation=None):
    if not gl_old or not gl_new: return

    page = 1
    per_page = 100 
    log_status(f"--- Migrating subgroups of Old Parent ID: {old_parent_group_id if old_parent_group_id else 'TOP LEVEL'} ---")

    while True:
        old_subgroups_list = []
        try:
            if old_parent_group_id:
                parent_obj_old = gl_old.groups.get(old_parent_group_id) # Need full object to list subgroups
                old_subgroups_list = parent_obj_old.subgroups.list(page=page, per_page=per_page, all=False) # as_list=False for paginated
            else: # Top-level groups
                old_subgroups_list = gl_old.groups.list(page=page, per_page=per_page, as_list=False, top_level_only=True)
        except Exception as e:
            log_status(f"ERROR fetching list of groups/subgroups for old_parent_id '{old_parent_group_id}': {e}")
            break # Stop for this parent

        if not old_subgroups_list:
            log_status(f"No more subgroups found for old parent ID '{old_parent_group_id if old_parent_group_id else 'TOP_LEVEL'}' on page {page}.")
            break

        for old_group_lazy in old_subgroups_list:
            old_group_full = get_full_group_object_old_gl(old_group_lazy.id)
            if not old_group_full:
                log_status(f"Could not get full object for old group ID {old_group_lazy.id}. Skipping.")
                continue

            log_status(f"Processing old group: '{old_group_full.full_path}' (Old ID: {old_group_full.id})")

            if old_group_full.id in OLD_TO_NEW_GROUP_ID_MAP:
                new_group_id_for_children = OLD_TO_NEW_GROUP_ID_MAP[old_group_full.id]
                log_status(f"  Group '{old_group_full.name}' already mapped: Old {old_group_full.id} -> New {new_group_id_for_children}. Recursively checking its subgroups.")
                migrate_groups_recursive_py(old_group_full.id, new_group_id_for_children)
                continue

            new_created_group_obj = create_or_find_group_on_new(old_group_full, new_parent_id_for_subgroup_creation)

            if new_created_group_obj:
                OLD_TO_NEW_GROUP_ID_MAP[old_group_full.id] = new_created_group_obj.id
                log_status(f"  MAP: Old Group ID {old_group_full.id} ('{old_group_full.name}') -> New Group ID {new_created_group_obj.id}")
                # Recurse for subgroups of *this* old_group, to be created under the new_created_group_obj
                migrate_groups_recursive_py(old_group_full.id, new_created_group_obj.id)
            else:
                log_status(f"  ERROR: Failed to create/map group '{old_group_full.name}'. Skipping its subgroups.")
        
        # Check if it was the last page based on GitLab's behavior (less than per_page items)
        # More robustly, check response headers for Link ; rel="next"
        if len(old_subgroups_list) < per_page:
            break
        page += 1

# (Keep migrate_project_repo_py and run_full_migration functions as they were in the previous complete script,
# ensuring the project creation part uses the mapped new group IDs and handles user namespaces)
# Make sure to call the updated migrate_groups_recursive_py from run_full_migration.
# The project listing part in run_full_migration also needs to handle potential NameResolutionError
# by ensuring old server's external_url is fixed or implementing manual pagination for projects.

# --- (The migrate_project_repo_py and run_full_migration from the previous complete script should be here) ---
# --- For brevity, I'm not repeating them, but ensure they are included and work with the above. ---
# --- Key part of run_full_migration for project listing that needs robustness: ---
def run_full_migration():
    global migration_status_log, OLD_TO_NEW_GROUP_ID_MAP, CREATED_PATHS_IN_NEW_NAMESPACE
    migration_status_log = []
    OLD_TO_NEW_GROUP_ID_MAP = {}
    CREATED_PATHS_IN_NEW_NAMESPACE = {}

    try:
        initialize_gitlab_clients()
    except Exception as e:
        log_status(f"Halting migration due to client initialization failure: {e}")
        return

    if os.path.exists(MIGRATION_TEMP_DIR):
        log_status(f"Cleaning up old migration temp directory: {MIGRATION_TEMP_DIR}")
        shutil.rmtree(MIGRATION_TEMP_DIR)
    os.makedirs(MIGRATION_TEMP_DIR, exist_ok=True)

    log_status("=== PHASE 1: Migrating Group Hierarchy ===")
    initial_new_parent_id = None
    if TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL:
        log_status(f"All groups will be migrated under pre-existing new group ID: {TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL}")
        initial_new_parent_id = TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL
    migrate_groups_recursive_py(None, initial_new_parent_id) # Pass None for old_parent to start top-level
    log_status("=== FINISHED PHASE 1: Group Hierarchy Migration ===")

    log_status("Final Group ID Map:")
    for old_id, new_id in OLD_TO_NEW_GROUP_ID_MAP.items():
        log_status(f"  Old Group ID: {old_id} -> New Group ID: {new_id}")

    log_status("=== PHASE 2: Migrating Projects and Repositories ===")
    migrated_project_repo_count = 0
    failed_project_repo_count = 0
    
    old_projects_list_full = []
    try:
        log_status("Attempting to fetch all projects from old GitLab...")
        # Using pagination manually if `all=True` with `keep_base_url=True` is still problematic
        # This is a more robust way if external_url on old server is intractably misconfigured
        page = 1
        per_page_projects = 50 # Can be up to 100
        while True:
            log_status(f"Fetching projects page {page} (per_page={per_page_projects}) from old GitLab...")
            projects_on_page = gl_old.projects.list(page=page, per_page=per_page_projects, archived=False, statistics=False, as_list=True)
            if not projects_on_page:
                log_status("No more projects on this page or subsequent pages.")
                break
            old_projects_list_full.extend(projects_on_page)
            if len(projects_on_page) < per_page_projects:
                log_status("Last page of projects fetched.")
                break
            page += 1
            time.sleep(0.1) # Small delay between page fetches
        log_status(f"Successfully fetched {len(old_projects_list_full)} projects from old GitLab.")
    except Exception as e:
        log_status(f"ERROR: Could not complete fetching project list from old GitLab: {e}")
        log_status("Migration task finished (or failed critically) due to project fetch error.")
        return

    log_status(f"Total projects to process: {len(old_projects_list_full)}.")

    for old_project_lazy in old_projects_list_full: # Iterate over the fetched list
        try:
            # Get full project object to ensure all attributes are available
            old_project = gl_old.projects.get(old_project_lazy.id)
            
            new_target_namespace_id = None
            if old_project.namespace['kind'] == 'group':
                if old_project.namespace['id'] in OLD_TO_NEW_GROUP_ID_MAP:
                    new_target_namespace_id = OLD_TO_NEW_GROUP_ID_MAP[old_project.namespace['id']]
                else:
                    log_status(f"WARNING: No new group mapping found for old group ID {old_project.namespace['id']} (project: {old_project.path_with_namespace}). Skipping project.")
                    failed_project_repo_count += 1
                    continue
            elif old_project.namespace['kind'] == 'user':
                log_status(f"Project '{old_project.name}' is a user project. Will be created under API token owner on new GitLab.")
            else:
                log_status(f"Unknown namespace kind for project {old_project.name}. Skipping.")
                failed_project_repo_count +=1
                continue

            if migrate_project_repo_py(old_project, new_target_namespace_id): # This function was defined in prior message
                migrated_project_repo_count += 1
            else:
                failed_project_repo_count += 1
            time.sleep(0.3) 

        except gitlab.exceptions.GitlabGetError as e_get_proj:
            log_status(f"ERROR: Could not fetch full details for old project ID {old_project_lazy.id}. Error: {e_get_proj}. Skipping.")
            failed_project_repo_count += 1
        except Exception as e_proj_loop:
            log_status(f"CRITICAL UNEXPECTED ERROR processing project loop for old ID {old_project_lazy.id}: {e_proj_loop}")
            failed_project_repo_count += 1


    log_status("=== MIGRATION COMPLETE ===")
    log_status(f"Successfully processed repositories for: {migrated_project_repo_count} projects.")
    log_status(f"Failed to process/migrate repositories for: {failed_project_repo_count} projects.")