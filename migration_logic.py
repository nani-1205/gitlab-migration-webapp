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

MIGRATION_TEMP_DIR = "./gitlab_migration_temp_python"

# --- Global state ---
migration_status_log = []
OLD_TO_NEW_GROUP_ID_MAP = {} # old_id -> new_id
CREATED_PATHS_IN_NEW_NAMESPACE = {} # namespace_id_new -> set(project_paths) to check for duplicates

gl_old = None
gl_new = None

def log_status(message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    full_message = f"[{timestamp}] {message}"
    print(full_message)
    migration_status_log.append(full_message)

def initialize_gitlab_clients():
    global gl_old, gl_new
    try:
        log_status(f"Initializing old GitLab client for URL: {OLD_GITLAB_URL}")
        # Using keep_base_url=True to prevent python-gitlab from changing the URL for pagination
        # This relies on OLD_GITLAB_URL being correctly set and resolvable.
        gl_old = gitlab.Gitlab(OLD_GITLAB_URL, private_token=OLD_GITLAB_TOKEN, timeout=30, keep_base_url=True)
        gl_old.auth()
        log_status("Old GitLab client authenticated.")
    except Exception as e:
        log_status(f"ERROR: Failed to initialize/authenticate old GitLab client: {e}")
        gl_old = None
        raise

    try:
        log_status(f"Initializing new GitLab client for URL: {NEW_GITLAB_URL}")
        gl_new = gitlab.Gitlab(NEW_GITLAB_URL, private_token=NEW_GITLAB_TOKEN, timeout=30, keep_base_url=True)
        gl_new.auth()
        log_status("New GitLab client authenticated.")
    except Exception as e:
        log_status(f"ERROR: Failed to initialize/authenticate new GitLab client: {e}")
        gl_new = None
        raise

def create_group_on_new(old_group_data, new_parent_id=None):
    global CREATED_PATHS_IN_NEW_NAMESPACE
    name = old_group_data.name
    path_slug = old_group_data.path
    visibility = old_group_data.visibility
    description = old_group_data.description or ""

    log_status(f"Attempting to create/find group '{name}' (path: {path_slug}) on new instance.")
    payload = {
        'name': name,
        'path': path_slug,
        'visibility': visibility,
        'description': description
    }
    if new_parent_id:
        payload['parent_id'] = new_parent_id
        log_status(f"  as subgroup of new parent ID: {new_parent_id}")

    # Check if group already exists to prevent "path has already been taken"
    try:
        search_path = f"{gl_new.groups.get(new_parent_id).full_path}/{path_slug}" if new_parent_id else path_slug
        existing_groups = gl_new.groups.list(search=search_path, all=True) # Search might not be exact for full_path
        for g in existing_groups:
            # More precise check for path and parent
            is_top_level_match = (not new_parent_id and not g.parent_id and g.path == path_slug)
            is_subgroup_match = (new_parent_id and g.parent_id == new_parent_id and g.path == path_slug)
            if is_top_level_match or is_subgroup_match:
                log_status(f"Group '{g.name}' (path: {g.path}) already exists on new instance with ID {g.id}. Using existing.")
                return gl_new.groups.get(g.id) # Return full object
    except Exception as e_search:
        log_status(f"  Note: Could not definitively check if group exists before creation: {e_search}")


    try:
        new_group = gl_new.groups.create(payload)
        log_status(f"Successfully created group '{new_group.name}' with NEW ID {new_group.id} on new instance.")
        return new_group # Is already a full object
    except gitlab.exceptions.GitlabCreateError as e:
        if "has already been taken" in str(e.error_message):
            log_status(f"Group '{name}' (path: {path_slug}) create failed as it's already taken. Attempting to fetch existing.")
            # Try to fetch it again by path and parent_id
            try:
                groups = gl_new.groups.list(search=path_slug, all=True)
                for group in groups:
                    is_top_level_match = (not new_parent_id and not group.parent_id and group.path == path_slug)
                    is_subgroup_match = (new_parent_id and group.parent_id == new_parent_id and group.path == path_slug)
                    if is_top_level_match or is_subgroup_match:
                        log_status(f"Found existing group '{group.name}' with ID {group.id} after create failure.")
                        return gl_new.groups.get(group.id) # Return full object
                log_status(f"Could not find existing group '{name}' (path: {path_slug}) after 'already taken' error.")
            except Exception as e_find:
                 log_status(f"Error trying to find existing group '{name}' after create failure: {e_find}")
        else:
            log_status(f"ERROR: Failed to create group '{name}' on new instance: {e.error_message} - Full response: {e.response_body}")
        return None
    except Exception as e_unexp:
        log_status(f"UNEXPECTED ERROR during group creation for '{name}': {e_unexp}")
        return None


def migrate_groups_recursive_py(old_parent_group_id_for_subgroup_listing=None, new_parent_group_id_for_creation=None):
    if not gl_old or not gl_new: return

    page = 1
    per_page = 100

    while True:
        old_groups_page = []
        if old_parent_group_id_for_subgroup_listing:
            try:
                parent_group_obj = gl_old.groups.get(old_parent_group_id_for_subgroup_listing)
                log_status(f"Fetching subgroups for old group: '{parent_group_obj.full_path}' (ID: {old_parent_group_id_for_subgroup_listing}), page {page}")
                old_groups_page = parent_group_obj.subgroups.list(page=page, per_page=per_page, as_list=False)
            except Exception as e:
                log_status(f"ERROR fetching subgroups for old parent ID {old_parent_group_id_for_subgroup_listing}: {e}")
                break
        else:
            log_status(f"Fetching top-level groups from old instance, page {page}")
            try:
                old_groups_page = gl_old.groups.list(page=page, per_page=per_page, as_list=False, top_level_only=True)
            except Exception as e:
                log_status(f"ERROR fetching top-level groups: {e}")
                break
        
        if not old_groups_page: # No more groups/subgroups on this page
            log_status(f"No more groups/subgroups found for old parent ID '{old_parent_group_id_for_subgroup_listing if old_parent_group_id_for_subgroup_listing else 'TOP_LEVEL'}' on page {page}.")
            break

        for old_group_lazy in old_groups_page:
            try:
                # Get the full group object as list() can return partial objects
                old_group = gl_old.groups.get(old_group_lazy.id)
                log_status(f"Processing old group: '{old_group.full_path}' (ID: {old_group.id})")

                if old_group.id in OLD_TO_NEW_GROUP_ID_MAP:
                    log_status(f"Group '{old_group.name}' (Old ID: {old_group.id}) already processed. New ID: {OLD_TO_NEW_GROUP_ID_MAP[old_group.id]}. Recursively checking its subgroups.")
                    new_group_id_for_children = OLD_TO_NEW_GROUP_ID_MAP[old_group.id]
                    migrate_groups_recursive_py(old_group.id, new_group_id_for_children)
                    continue

                # Create this group on the new instance, under new_parent_group_id_for_creation
                new_created_group_obj = create_group_on_new(old_group, new_parent_group_id_for_creation)

                if new_created_group_obj:
                    OLD_TO_NEW_GROUP_ID_MAP[old_group.id] = new_created_group_obj.id
                    log_status(f"MAP: Old Group ID {old_group.id} ('{old_group.name}') -> New Group ID {new_created_group_obj.id}")
                    # Recurse for subgroups of this old_group, they will be created under new_created_group_obj.id
                    migrate_groups_recursive_py(old_group.id, new_created_group_obj.id)
                else:
                    log_status(f"ERROR: Failed to create/map group '{old_group.name}'. Skipping its subgroups.")

            except gitlab.exceptions.GitlabGetError as e_get:
                 log_status(f"ERROR: Could not fully fetch old group object with ID {old_group_lazy.id}. Details: {e_get}. Skipping this group and its potential subgroups.")
            except Exception as e_loop:
                log_status(f"ERROR: Unexpected error processing old group ID {old_group_lazy.id if old_group_lazy else 'N/A'}: {e_loop}")
        
        if len(old_groups_page) < per_page: # This was the last page
            break
        page += 1


def migrate_project_repo_py(old_project_obj, new_target_namespace_id):
    global CREATED_PATHS_IN_NEW_NAMESPACE
    log_status(f"--- Processing Old Project: '{old_project_obj.path_with_namespace}' (ID: {old_project_obj.id}) ---")

    project_payload = {
        'name': old_project_obj.name,
        'path': old_project_obj.path,
        'description': old_project_obj.description or "",
        'visibility': old_project_obj.visibility,
        'initialize_with_readme': False # Crucial for push --mirror
    }
    if new_target_namespace_id: # If it's a group
        project_payload['namespace_id'] = new_target_namespace_id
        log_status(f"  Targeting New Mapped Group ID: {new_target_namespace_id} for project '{old_project_obj.name}'")
    else: # User namespace project, create under token owner
        log_status(f"  Targeting user namespace of API token owner on new instance for project '{old_project_obj.name}'.")
        # No namespace_id in payload means it goes to the token owner's user space

    # Check for duplicate path within the target namespace
    namespace_key = str(new_target_namespace_id) if new_target_namespace_id else "user_namespace"
    if namespace_key not in CREATED_PATHS_IN_NEW_NAMESPACE:
        CREATED_PATHS_IN_NEW_NAMESPACE[namespace_key] = set()
    
    if old_project_obj.path in CREATED_PATHS_IN_NEW_NAMESPACE[namespace_key]:
        log_status(f"ERROR: Project path '{old_project_obj.path}' already attempted or created in namespace '{namespace_key}'. Trying to find existing.")
        # Attempt to find the existing project
        try:
            if new_target_namespace_id:
                ns_obj = gl_new.groups.get(new_target_namespace_id)
                projects_in_ns = ns_obj.projects.list(search=old_project_obj.path, all=True)
            else: # User's own namespace
                projects_in_ns = gl_new.projects.list(owned=True, search=old_project_obj.path, all=True)
            
            found_project = next((p for p in projects_in_ns if p.path == old_project_obj.path), None)
            if found_project:
                log_status(f"Found existing project '{found_project.name}' with ID {found_project.id}. Will attempt to push to it.")
                new_project = found_project
            else:
                log_status(f"Could not find existing project with path '{old_project_obj.path}' in namespace '{namespace_key}'. Skipping this project.")
                return False
        except Exception as e_find:
            log_status(f"Error trying to find existing project: {e_find}. Skipping project '{old_project_obj.name}'.")
            return False
    else:
        try:
            log_status(f"Creating project with payload: {project_payload}")
            new_project = gl_new.projects.create(project_payload)
            log_status(f"Successfully created new project '{new_project.name}' (New ID: {new_project.id}) on new instance.")
            CREATED_PATHS_IN_NEW_NAMESPACE[namespace_key].add(new_project.path)
        except gitlab.exceptions.GitlabCreateError as e:
            log_status(f"ERROR: Failed to create project '{old_project_obj.name}' on new instance: {e.error_message} - Full response: {e.response_body}")
            # If it was "path has already been taken", we add to set to avoid retrying identical path
            if "has already been taken" in str(e.error_message) or "path already exists" in str(e.error_message).lower() :
                 CREATED_PATHS_IN_NEW_NAMESPACE[namespace_key].add(old_project_obj.path)
            return False
        except Exception as e_unexp_proj:
            log_status(f"UNEXPECTED ERROR during project creation for '{old_project_obj.name}': {e_unexp_proj}")
            return False

    # --- Git Operations ---
    old_repo_url = f"ssh://git@{OLD_GITLAB_SSH_HOST}:{OLD_GITLAB_SSH_PORT}/{old_project_obj.path_with_namespace}.git"
    new_repo_url = f"ssh://git@{NEW_GITLAB_SSH_HOST}:{NEW_GITLAB_SSH_PORT}/{new_project.path_with_namespace}.git"
    log_status(f"Old Repo URL for clone: {old_repo_url}")
    log_status(f"New Repo URL for push: {new_repo_url}")

    temp_repo_path = os.path.join(MIGRATION_TEMP_DIR, f"{old_project_obj.path.replace('/', '_')}_{old_project_obj.id}_{int(time.time())}.git")
    if os.path.exists(temp_repo_path): shutil.rmtree(temp_repo_path)

    log_status(f"Cloning (mirror) '{old_repo_url}' to '{temp_repo_path}'...")
    clone_proc = subprocess.run(['git', 'clone', '--mirror', old_repo_url, temp_repo_path], capture_output=True, text=True, check=False)
    if clone_proc.returncode != 0:
        if "empty repository" in clone_proc.stderr.lower():
            log_status(f"INFO: Old project '{old_project_obj.path_with_namespace}' is empty. Repo created on new instance, skipping push.")
            shutil.rmtree(temp_repo_path, ignore_errors=True)
            return True # Still a success for project creation
        log_status(f"ERROR: Failed to clone '{old_repo_url}'. Stderr: {clone_proc.stderr}")
        shutil.rmtree(temp_repo_path, ignore_errors=True)
        return False

    log_status(f"Pushing (mirror) from '{temp_repo_path}' to new remote '{new_repo_url}'...")
    push_proc = subprocess.run(['git', '--git-dir', temp_repo_path, 'push', '--mirror', new_repo_url], capture_output=True, text=True, check=False)
    shutil.rmtree(temp_repo_path, ignore_errors=True)

    if push_proc.returncode != 0:
        if "deny updating a hidden ref" in push_proc.stderr or "rpc error: code = Canceled" in push_proc.stderr:
            log_status(f"WARNING: Push to '{new_repo_url}' had rejections for internal refs, but user branches/tags likely pushed. Stderr: {push_proc.stderr}")
            return True 
        log_status(f"ERROR: Failed to push (mirror) to '{new_repo_url}'. Stderr: {push_proc.stderr}")
        return False
    
    log_status(f"Successfully migrated Git data for '{old_project_obj.path_with_namespace}'.")
    return True


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
    # Decide if you want all migrated groups under one pre-existing new group.
    # If so, get that pre-existing group's ID on the new instance and pass it as the second argument.
    # Example: migrate_groups_recursive_py(None, 355) # where 355 is your target parent group on new GitLab
    # For creating top-level groups as they were on old instance:
    migrate_groups_recursive_py(None, None)
    log_status("=== FINISHED PHASE 1: Group Hierarchy Migration ===")

    log_status("Final Group ID Map:")
    for old_id, new_id in OLD_TO_NEW_GROUP_ID_MAP.items():
        log_status(f"  Old Group ID: {old_id} -> New Group ID: {new_id}")

    log_status("=== PHASE 2: Migrating Projects and Repositories ===")
    migrated_project_repo_count = 0
    failed_project_repo_count = 0
    
    try:
        # Get all projects user has access to, not just owned, and not archived
        old_projects = gl_old.projects.list(all=True, archived=False) 
    except Exception as e:
        log_status(f"ERROR: Could not fetch project list from old GitLab: {e}")
        return

    log_status(f"Found {len(old_projects)} projects to process from old instance.")

    for old_project_lazy in old_projects:
        try:
            # Get full project object
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
                # new_target_namespace_id remains None for user projects under token owner
            else:
                log_status(f"Unknown namespace kind for project {old_project.name}. Skipping.")
                failed_project_repo_count +=1
                continue

            if migrate_project_repo_py(old_project, new_target_namespace_id):
                migrated_project_repo_count += 1
            else:
                failed_project_repo_count += 1
            time.sleep(0.3) # Be a bit nice to APIs

        except gitlab.exceptions.GitlabGetError as e_get_proj:
            log_status(f"ERROR: Could not fetch full details for old project ID {old_project_lazy.id}. Error: {e_get_proj}. Skipping.")
            failed_project_repo_count += 1
        except Exception as e_proj_loop:
            log_status(f"CRITICAL UNEXPECTED ERROR processing project loop for old ID {old_project_lazy.id}: {e_proj_loop}")
            failed_project_repo_count += 1


    log_status("=== MIGRATION COMPLETE ===")
    log_status(f"Successfully processed repositories for: {migrated_project_repo_count} projects.")
    log_status(f"Failed to process/migrate repositories for: {failed_project_repo_count} projects.")

# If you want to run this script directly without Flask for testing:
# if __name__ == '__main__':
#     run_full_migration()
#     print("\n--- Full Migration Log (from migration_status_log array) ---")
#     for entry in migration_status_log:
#         print(entry)