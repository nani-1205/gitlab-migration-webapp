import gitlab
import os
import subprocess
import shutil
import time
from dotenv import load_dotenv
import json # For escaping description

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

# If you want all migrated groups to be under a specific pre-existing group on the new GitLab,
# set its ID here. Otherwise, set to None or leave blank in .env to create top-level groups.
TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = os.getenv('TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL', None)
if TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL:
    try:
        TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = int(TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL)
    except (ValueError, TypeError):
        print(f"WARNING: TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL ('{TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL}') in .env is not a valid integer. Creating groups at top level.")
        TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = None


MIGRATION_TEMP_DIR = "./gitlab_migration_temp_python_v4" # Incremented version for temp dir

# --- Global state ---
migration_status_log = []
OLD_TO_NEW_GROUP_ID_MAP = {}  # old_id -> new_id
# Key: new_namespace_id (str) or "user_namespace_for_token_owner", Value: set of project_paths (slugs)
CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE = {} 

gl_old = None
gl_new = None

def log_status(message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    full_message = f"[{timestamp}] {message}"
    print(full_message)
    migration_status_log.append(full_message)

def initialize_gitlab_clients():
    global gl_old, gl_new
    log_status("--- Initializing GitLab Clients ---")
    try:
        log_status(f"Old GitLab Client: URL={OLD_GITLAB_URL}")
        gl_old = gitlab.Gitlab(OLD_GITLAB_URL, private_token=OLD_GITLAB_TOKEN, timeout=45, keep_base_url=True)
        gl_old.auth()
        log_status("Old GitLab client authenticated successfully.")
    except Exception as e:
        log_status(f"FATAL ERROR: Failed to initialize/authenticate old GitLab client: {e}")
        gl_old = None
        raise

    try:
        log_status(f"New GitLab Client: URL={NEW_GITLAB_URL}")
        gl_new = gitlab.Gitlab(NEW_GITLAB_URL, private_token=NEW_GITLAB_TOKEN, timeout=45, keep_base_url=True)
        gl_new.auth()
        log_status("New GitLab client authenticated successfully.")
    except Exception as e:
        log_status(f"FATAL ERROR: Failed to initialize/authenticate new GitLab client: {e}")
        gl_new = None
        raise
    log_status("--- GitLab Clients Initialized ---")

def get_full_group_object(gl_instance, group_id_or_lazy_obj, context="old"):
    """Helper to ensure we have a full group object from a GitLab instance."""
    if not gl_instance: return None
    try:
        group_id = group_id_or_lazy_obj.id if hasattr(group_id_or_lazy_obj, 'id') else group_id_or_lazy_obj
        return gl_instance.groups.get(group_id)
    except Exception as e:
        log_status(f"ERROR: Could not get full group object for {context}_id {group_id}: {e}")
        return None

def create_or_find_group_on_new(old_group_obj_full, new_parent_id_for_creation=None):
    name = old_group_obj_full.name
    path_slug = old_group_obj_full.path
    visibility = old_group_obj_full.visibility
    description = old_group_obj_full.description or ""

    log_status(f"Attempting to create/find group '{name}' (Path: {path_slug}) on new instance.")
    if new_parent_id_for_creation:
        log_status(f"  Targeting new parent group ID: {new_parent_id_for_creation}")

    # Attempt to find existing group first more robustly
    try:
        if new_parent_id_for_creation:
            parent_group_new = gl_new.groups.get(new_parent_id_for_creation)
            subgroups = parent_group_new.subgroups.list(all=True)
            for sg in subgroups:
                if sg.path == path_slug:
                    log_status(f"Group '{name}' (Path: {path_slug}) already exists as subgroup of {new_parent_id_for_creation} with NEW ID {sg.id}. Using it.")
                    return gl_new.groups.get(sg.id) # Return full object
        else: # Top-level group
            groups = gl_new.groups.list(search=path_slug, all=True) # Search can be fuzzy
            for g in groups:
                if g.path == path_slug and g.parent_id is None:
                    log_status(f"Group '{name}' (Path: {path_slug}) already exists as top-level with NEW ID {g.id}. Using it.")
                    return gl_new.groups.get(g.id) # Return full object
    except Exception as e_find_first:
        log_status(f"Note: Error during initial check for group '{name}': {e_find_first}. Will proceed to create.")

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
        log_status(f"Creating group with payload: {json.dumps(payload)}") # Log payload for debugging
        new_group = gl_new.groups.create(payload)
        log_status(f"Successfully created group '{new_group.name}' with NEW ID {new_group.id}.")
        return new_group # This is a full object from create
    except gitlab.exceptions.GitlabCreateError as e:
        log_status(f"ERROR: Failed to create group '{name}' (Path: {path_slug}). API Message: {e.error_message}. Full Response: {e.response_body}")
        # If it failed because it was "already taken", it means our initial find might have missed it (e.g. due to search limitations)
        # No need to re-find here, as the earlier find block should have caught it if re-run.
        return None
    except Exception as e_unexp:
        log_status(f"UNEXPECTED ERROR creating group '{name}': {e_unexp}")
        return None

def migrate_groups_recursive_py(old_parent_group_id_for_subgroup_listing=None, new_parent_id_for_creation=None):
    if not gl_old or not gl_new: return

    page = 1
    per_page = 100 
    log_status(f"--- Migrating subgroups of Old Parent ID: {old_parent_group_id_for_subgroup_listing if old_parent_group_id_for_subgroup_listing else 'TOP LEVEL'} into New Parent ID: {new_parent_id_for_creation if new_parent_id_for_creation else 'TOP LEVEL'} ---")

    while True:
        old_subgroups_page_lazy = []
        try:
            if old_parent_group_id_for_subgroup_listing:
                # Need full parent object to list subgroups
                parent_obj_old = get_full_group_object(gl_old, old_parent_group_id_for_subgroup_listing, "old parent")
                if not parent_obj_old: break # Could not get parent
                log_status(f"Fetching subgroups for old group: '{parent_obj_old.full_path}' (ID: {old_parent_group_id_for_subgroup_listing}), page {page}")
                old_subgroups_page_lazy = parent_obj_old.subgroups.list(page=page, per_page=per_page, as_list=False)
            else: # Top-level groups
                log_status(f"Fetching top-level groups from old instance, page {page}")
                old_subgroups_page_lazy = gl_old.groups.list(page=page, per_page=per_page, as_list=False, top_level_only=True)
        except Exception as e:
            log_status(f"ERROR fetching list of groups/subgroups for old_parent_id '{old_parent_group_id_for_subgroup_listing}': {e}")
            break 

        if not old_subgroups_page_lazy:
            log_status(f"No more groups/subgroups found for old parent ID '{old_parent_group_id_for_subgroup_listing if old_parent_group_id_for_subgroup_listing else 'TOP_LEVEL'}' on page {page}.")
            break

        for old_group_lazy_item in old_subgroups_page_lazy:
            old_group_full = get_full_group_object(gl_old, old_group_lazy_item.id, "old current")
            if not old_group_full:
                log_status(f"Could not get full object for old group ID {old_group_lazy_item.id}. Skipping.")
                continue

            log_status(f"Processing old group: '{old_group_full.full_path}' (Old ID: {old_group_full.id})")

            if old_group_full.id in OLD_TO_NEW_GROUP_ID_MAP:
                new_group_id_for_children = OLD_TO_NEW_GROUP_ID_MAP[old_group_full.id]
                log_status(f"  Group '{old_group_full.name}' already mapped: Old {old_group_full.id} -> New {new_group_id_for_children}. Recursively checking its subgroups.")
                migrate_groups_recursive_py(old_group_full.id, new_group_id_for_children)
                continue

            new_created_group_obj = create_or_find_group_on_new(old_group_full, new_parent_id_for_creation)

            if new_created_group_obj:
                OLD_TO_NEW_GROUP_ID_MAP[old_group_full.id] = new_created_group_obj.id
                log_status(f"  MAP: Old Group ID {old_group_full.id} ('{old_group_full.name}') -> New Group ID {new_created_group_obj.id}")
                migrate_groups_recursive_py(old_group_full.id, new_created_group_obj.id)
            else:
                log_status(f"  ERROR: Failed to create/map group '{old_group_full.name}'. Skipping its subgroups.")
        
        if len(old_subgroups_page_lazy) < per_page: break
        page += 1
        time.sleep(0.1) # API kindness

def migrate_project_repo_py(old_project_full, new_target_namespace_id):
    global CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE
    log_status(f"--- Processing Old Project: '{old_project_full.path_with_namespace}' (ID: {old_project_full.id}) ---")

    project_payload = {
        'name': old_project_full.name,
        'path': old_project_full.path,
        'description': old_project_full.description or "",
        'visibility': old_project_full.visibility,
        'initialize_with_readme': False
    }

    namespace_key_for_duplicate_check = "user_namespace_token_owner" # Default for user projects
    if new_target_namespace_id:
        project_payload['namespace_id'] = new_target_namespace_id
        namespace_key_for_duplicate_check = str(new_target_namespace_id)
        log_status(f"  Targeting New Mapped Group ID: {new_target_namespace_id} for project '{old_project_full.name}'")
    else:
        log_status(f"  Targeting user namespace of API token owner on new instance for project '{old_project_full.name}'.")

    if namespace_key_for_duplicate_check not in CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE:
        CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check] = set()
    
    new_project = None # Initialize
    if old_project_full.path in CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check]:
        log_status(f"Project path '{old_project_full.path}' already processed for namespace '{namespace_key_for_duplicate_check}'. Attempting to find existing project.")
        try:
            if new_target_namespace_id:
                ns_obj = gl_new.groups.get(new_target_namespace_id)
                projects_in_ns = ns_obj.projects.list(search=old_project_full.path, all=True, lazy=True)
            else: 
                projects_in_ns = gl_new.projects.list(owned=True, search=old_project_full.path, all=True, lazy=True)
            
            found_project_lazy = next((p for p in projects_in_ns if p.path == old_project_full.path), None)
            if found_project_lazy:
                new_project = gl_new.projects.get(found_project_lazy.id) # Get full object
                log_status(f"Found existing project '{new_project.name}' with ID {new_project.id}. Will attempt to push to it.")
            else:
                log_status(f"Could not find existing project with path '{old_project_full.path}' in namespace '{namespace_key_for_duplicate_check}'. Skipping this project.")
                return False
        except Exception as e_find:
            log_status(f"Error trying to find existing project '{old_project_full.name}': {e_find}. Skipping.")
            return False
    else:
        try:
            log_status(f"Creating project with payload: {json.dumps(project_payload)}")
            new_project = gl_new.projects.create(project_payload)
            log_status(f"Successfully created new project '{new_project.name}' (New ID: {new_project.id}) on new instance.")
            CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check].add(new_project.path)
        except gitlab.exceptions.GitlabCreateError as e:
            err_msg_lower = str(e.error_message).lower()
            if "has already been taken" in err_msg_lower or "path already exists" in err_msg_lower:
                log_status(f"Project path '{old_project_full.path}' resulted in 'already taken' error. Marking as processed and attempting to find.")
                CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check].add(old_project_full.path)
                # Retry finding it, similar to above block
                try:
                    if new_target_namespace_id:
                        ns_obj = gl_new.groups.get(new_target_namespace_id)
                        projects_in_ns = ns_obj.projects.list(search=old_project_full.path, all=True, lazy=True)
                    else:
                        projects_in_ns = gl_new.projects.list(owned=True, search=old_project_full.path, all=True, lazy=True)
                    found_project_lazy = next((p for p in projects_in_ns if p.path == old_project_full.path), None)
                    if found_project_lazy:
                        new_project = gl_new.projects.get(found_project_lazy.id)
                        log_status(f"Found existing project '{new_project.name}' with ID {new_project.id} after 'already taken' error.")
                    else:
                        log_status(f"Could not find existing project with path '{old_project_full.path}' in namespace '{namespace_key_for_duplicate_check}' after 'already taken'. Skipping.")
                        return False
                except Exception as e_find_after_create_fail:
                    log_status(f"Error finding existing project after 'already taken': {e_find_after_create_fail}. Skipping '{old_project_full.name}'.")
                    return False
            else:
                log_status(f"ERROR: Failed to create project '{old_project_full.name}'. API Message: {e.error_message}. Full Response: {e.response_body}")
                return False
        except Exception as e_unexp_proj:
            log_status(f"UNEXPECTED ERROR during project creation for '{old_project_full.name}': {e_unexp_proj}")
            return False

    if not new_project: # Should not happen if logic above is correct, but as a safeguard
        log_status(f"ERROR: new_project object is None for old project '{old_project_full.name}'. Cannot proceed with git operations.")
        return False

    # --- Git Operations ---
    old_repo_url = f"ssh://git@{OLD_GITLAB_SSH_HOST}:{OLD_GITLAB_SSH_PORT}/{old_project_full.path_with_namespace}.git"
    new_repo_url = f"ssh://git@{NEW_GITLAB_SSH_HOST}:{NEW_GITLAB_SSH_PORT}/{new_project.path_with_namespace}.git"
    log_status(f"Old Repo URL for clone: {old_repo_url}")
    log_status(f"New Repo URL for push: {new_repo_url}")

    # Sanitize path for directory name
    safe_path_old = old_project_full.path.replace('/', '_')
    temp_repo_path = os.path.join(MIGRATION_TEMP_DIR, f"{safe_path_old}_{old_project_full.id}_{int(time.time() * 1000)}.git")
    
    if os.path.exists(temp_repo_path): shutil.rmtree(temp_repo_path) # Should be unique now

    log_status(f"Cloning (mirror) '{old_repo_url}' to '{temp_repo_path}'...")
    clone_proc = subprocess.run(['git', 'clone', '--mirror', old_repo_url, temp_repo_path], capture_output=True, text=True, check=False)
    if clone_proc.returncode != 0:
        if "empty repository" in clone_proc.stderr.lower():
            log_status(f"INFO: Old project '{old_project_full.path_with_namespace}' is empty. Repo created on new instance, skipping push.")
            shutil.rmtree(temp_repo_path, ignore_errors=True)
            return True 
        log_status(f"ERROR: Failed to clone '{old_repo_url}'. Stderr: {clone_proc.stderr}")
        shutil.rmtree(temp_repo_path, ignore_errors=True)
        return False

    log_status(f"Pushing (mirror) from '{temp_repo_path}' to new remote '{new_repo_url}'...")
    # Using subprocess for more control and to avoid GitPython complexities with bare repos and remotes
    try:
        subprocess.run(['git', '--git-dir', temp_repo_path, 'remote', 'add', 'aws-target', new_repo_url], check=True, capture_output=True, text=True)
        push_proc = subprocess.run(['git', '--git-dir', temp_repo_path, 'push', '--mirror', 'aws-target'], capture_output=True, text=True, check=False)
    except subprocess.CalledProcessError as e_remote:
        log_status(f"ERROR adding remote for '{new_repo_url}'. Stderr: {e_remote.stderr}")
        shutil.rmtree(temp_repo_path, ignore_errors=True)
        return False
    finally:
        shutil.rmtree(temp_repo_path, ignore_errors=True)


    if push_proc.returncode != 0:
        # "deny updating a hidden ref" and "rpc error: code = Canceled desc = user canceled the push" are often ignorable for --mirror of internal refs
        if "deny updating a hidden ref" in push_proc.stderr or "rpc error: code = Canceled" in push_proc.stderr or "No refs in common" in push_proc.stdout:
            log_status(f"INFO/WARNING: Push to '{new_repo_url}' had non-critical messages or rejections for internal refs. User branches/tags likely pushed. Stdout: {push_proc.stdout} Stderr: {push_proc.stderr}")
            return True # Count as success
        log_status(f"ERROR: Failed to push (mirror) to '{new_repo_url}'. Stdout: {push_proc.stdout} Stderr: {push_proc.stderr}")
        return False
    
    log_status(f"Successfully migrated Git data for '{old_project_full.path_with_namespace}'.")
    return True


def run_full_migration():
    global migration_status_log, OLD_TO_NEW_GROUP_ID_MAP, CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE
    migration_status_log = [] 
    OLD_TO_NEW_GROUP_ID_MAP = {}
    CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE = {}

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
    initial_new_parent_id_for_all_groups = None
    if TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL:
        log_status(f"All migrated groups will be created under pre-existing new group ID: {TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL}")
        initial_new_parent_id_for_all_groups = TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL
    
    migrate_groups_recursive_py(None, initial_new_parent_id_for_all_groups)
    log_status("=== FINISHED PHASE 1: Group Hierarchy Migration ===")
    log_status("Final Group ID Map:")
    for old_id, new_id in OLD_TO_NEW_GROUP_ID_MAP.items():
        log_status(f"  Old Group ID: {old_id} -> New Group ID: {new_id}")

    log_status("=== PHASE 2: Migrating Projects and Repositories ===")
    projects_migrated_count = 0
    projects_failed_count = 0
    
    old_projects_list_full = []
    try:
        log_status("Attempting to fetch all projects from old GitLab using MANUAL pagination...")
        page = 1
        per_page_projects = 20 # Keep this low if old server is unstable
        
        while True:
            log_status(f"Fetching projects page {page} (per_page={per_page_projects}) from old GitLab...")
            # Get lazy list for current page
            projects_on_page_lazy = gl_old.projects.list(page=page, per_page=per_page_projects, archived=False, statistics=False, as_list=False, all=False) 
            
            current_page_items = []
            for p_lazy in projects_on_page_lazy: # Iterate through the paginated object for current page
                current_page_items.append(p_lazy)
            
            if not current_page_items:
                log_status("No more projects found on this page or subsequent pages.")
                break
            
            old_projects_list_full.extend(current_page_items)
            log_status(f"Fetched {len(current_page_items)} projects on page {page}. Total fetched so far: {len(old_projects_list_full)}")

            if len(current_page_items) < per_page_projects:
                log_status("Likely the last page of projects fetched.")
                break
            
            page += 1
            time.sleep(0.2) # Be nice between page fetches
            
    except Exception as e:
        log_status(f"ERROR: Could not complete fetching project list from old GitLab: {e}")
        log_status("Migration task finished (or failed critically) due to project fetch error.")
        return

    log_status(f"Total projects fetched for processing: {len(old_projects_list_full)}.")

    for old_project_lazy_item in old_projects_list_full:
        try:
            log_status(f"Fetching full details for old project ID {old_project_lazy_item.id} ({old_project_lazy_item.path_with_namespace})...")
            old_project_full = gl_old.projects.get(old_project_lazy_item.id) # Get full object
            
            new_target_namespace_id = None
            if old_project_full.namespace['kind'] == 'group':
                if old_project_full.namespace['id'] in OLD_TO_NEW_GROUP_ID_MAP:
                    new_target_namespace_id = OLD_TO_NEW_GROUP_ID_MAP[old_project_full.namespace['id']]
                else:
                    log_status(f"WARNING: No new group mapping for old group ID {old_project_full.namespace['id']} (project: {old_project_full.path_with_namespace}). Skipping project.")
                    projects_failed_count += 1
                    continue
            elif old_project_full.namespace['kind'] == 'user':
                log_status(f"Project '{old_project_full.name}' is a user project. Will be created under API token owner on new GitLab.")
                # new_target_namespace_id remains None, project_payload will not include namespace_id
            else:
                log_status(f"Unknown namespace kind '{old_project_full.namespace['kind']}' for project '{old_project_full.name}'. Skipping.")
                projects_failed_count +=1
                continue

            if migrate_project_repo_py(old_project_full, new_target_namespace_id):
                projects_migrated_count += 1
            else:
                projects_failed_count += 1
            time.sleep(0.5) # Delay between processing each project

        except gitlab.exceptions.GitlabHttpError as e_get_proj: # Catch specific 500s here
             log_status(f"HTTP ERROR fetching full details for old project ID {old_project_lazy_item.id}: {e_get_proj.error_message} (Status: {e_get_proj.response_code}). Skipping.")
             projects_failed_count += 1
        except Exception as e_proj_loop:
            log_status(f"CRITICAL UNEXPECTED ERROR processing project loop for old ID {old_project_lazy_item.id}: {e_proj_loop}")
            projects_failed_count += 1

    log_status("=== MIGRATION COMPLETE ===")
    log_status(f"Projects where Git data migration was successful or repo was empty: {projects_migrated_count}")
    log_status(f"Projects that failed some part of the process (creation, clone, or push): {projects_failed_count}")
    log_status("Migration script finished.")

# To run this script directly for testing without Flask:
if __name__ == '__main__':
    log_status("Starting migration directly via __main__ for testing.")
    run_full_migration()
    print("\n--- Full Migration Log (from migration_status_log array) ---")
    for entry in migration_status_log:
        print(entry)