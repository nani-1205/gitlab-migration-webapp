import gitlab
import os
import subprocess
import shutil
import time
from dotenv import load_dotenv
import json

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

TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = os.getenv('TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL', None)
if TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL:
    try:
        TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = int(TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL)
    except (ValueError, TypeError):
        print(f"WARNING: TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL ('{TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL}') not valid. Creating groups at top level.")
        TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = None

MIGRATION_TEMP_DIR = "./gitlab_migration_temp_python_v5"

migration_status_log = []
OLD_TO_NEW_GROUP_ID_MAP = {}
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
    # ... (keep initialize_gitlab_clients as it was - good) ...
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
    # ... (keep get_full_group_object as it was - good) ...
    if not gl_instance: return None
    try:
        group_id = group_id_or_lazy_obj.id if hasattr(group_id_or_lazy_obj, 'id') else group_id_or_lazy_obj
        return gl_instance.groups.get(group_id)
    except Exception as e:
        log_status(f"ERROR: Could not get full group object for {context}_id {group_id}: {e}")
        return None

def create_or_find_group_on_new(old_group_obj_full, new_parent_id_for_creation=None):
    # ... (keep create_or_find_group_on_new as it was - good) ...
    global CREATED_PATHS_IN_NEW_NAMESPACE 
    
    name = old_group_obj_full.name
    path_slug = old_group_obj_full.path
    visibility = old_group_obj_full.visibility
    description = old_group_obj_full.description or ""

    log_status(f"Attempting to create/find group '{name}' (Path: {path_slug}) on new instance.")
    if new_parent_id_for_creation:
        log_status(f"  Targeting new parent group ID: {new_parent_id_for_creation}")

    try:
        candidate_groups = []
        if new_parent_id_for_creation:
            try:
                parent_group_new = gl_new.groups.get(new_parent_id_for_creation)
                all_subgroups = parent_group_new.subgroups.list(all=True)
                candidate_groups = [sg for sg in all_subgroups if sg.path == path_slug]
            except gitlab.exceptions.GitlabGetError:
                log_status(f"ERROR: New parent group ID {new_parent_id_for_creation} not found. Cannot create subgroup '{name}'.")
                return None
        else: 
            groups_from_search = gl_new.groups.list(search=path_slug, all=True)
            candidate_groups = [g for g in groups_from_search if g.path == path_slug and g.parent_id is None]

        if candidate_groups:
            existing_group = gl_new.groups.get(candidate_groups[0].id) 
            log_status(f"Group '{existing_group.name}' (Path: {existing_group.path}) already exists with NEW ID {existing_group.id}. Using it.")
            return existing_group
    except Exception as e_check:
        log_status(f"Warning: Error during pre-check for group '{name}': {e_check}. Proceeding with creation attempt.")

    payload = {
        'name': name, 'path': path_slug, 'visibility': visibility, 'description': description
    }
    if new_parent_id_for_creation: payload['parent_id'] = new_parent_id_for_creation
    
    try:
        log_status(f"Creating group with payload: {json.dumps(payload)}")
        new_group = gl_new.groups.create(payload)
        log_status(f"Successfully created group '{new_group.name}' with NEW ID {new_group.id}.")
        return new_group
    except gitlab.exceptions.GitlabCreateError as e:
        log_status(f"ERROR: Failed to create group '{name}' (Path: {path_slug}). API Message: {e.error_message}. Full Response: {e.response_body}")
        if "has already been taken" in str(e.error_message).lower() or "path already exists" in str(e.error_message).lower():
             log_status(f"  Retrying find for group '{path_slug}' after 'already taken' error.")
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

def migrate_groups_recursive_py(old_parent_group_id_for_subgroup_listing=None, new_parent_id_for_creation=None):
    # ... (keep migrate_groups_recursive_py as it was - good) ...
    if not gl_old or not gl_new: return
    page = 1; per_page = 100
    log_status(f"--- Migrating subgroups of Old Parent ID: {old_parent_group_id_for_subgroup_listing if old_parent_group_id_for_subgroup_listing else 'TOP LEVEL'} into New Parent ID: {new_parent_id_for_creation if new_parent_id_for_creation else 'TOP LEVEL'} ---")
    while True:
        old_subgroups_page_lazy = []
        try:
            if old_parent_group_id_for_subgroup_listing:
                parent_obj_old = get_full_group_object(gl_old, old_parent_group_id_for_subgroup_listing, "old parent")
                if not parent_obj_old: break
                log_status(f"Fetching subgroups for old group: '{parent_obj_old.full_path}' (ID: {old_parent_group_id_for_subgroup_listing}), page {page}")
                old_subgroups_page_lazy = parent_obj_old.subgroups.list(page=page, per_page=per_page, as_list=False)
            else:
                log_status(f"Fetching top-level groups from old instance, page {page}")
                old_subgroups_page_lazy = gl_old.groups.list(page=page, per_page=per_page, as_list=False, top_level_only=True)
        except Exception as e:
            log_status(f"ERROR fetching list of groups/subgroups for old_parent_id '{old_parent_group_id_for_subgroup_listing}': {e}"); break
        if not old_subgroups_page_lazy:
            log_status(f"No more groups/subgroups for old parent ID '{old_parent_group_id_for_subgroup_listing if old_parent_group_id_for_subgroup_listing else 'TOP_LEVEL'}' on page {page}."); break
        for old_group_lazy_item in old_subgroups_page_lazy:
            old_group_full = get_full_group_object(gl_old, old_group_lazy_item.id, "old current")
            if not old_group_full: log_status(f"Could not get full object for old group ID {old_group_lazy_item.id}. Skipping."); continue
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
        page += 1; time.sleep(0.1)

def migrate_project_repo_py(old_project_stub, new_target_namespace_id): # Changed to accept old_project_stub
    global CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE
    # Use attributes directly from old_project_stub if available
    # The list() call should provide these for non-archived projects
    project_id_old = old_project_stub.id
    project_name_old = old_project_stub.name
    project_path_old = old_project_stub.path
    project_namespace_path_old = old_project_stub.path_with_namespace
    project_description_old = old_project_stub.description or ""
    project_visibility_old = old_project_stub.visibility
    # IMPORTANT: Get ssh_url_to_repo from the stub if present!
    old_repo_url_from_stub = old_project_stub.attributes.get('ssh_url_to_repo')

    log_status(f"--- Processing Old Project STUB: '{project_namespace_path_old}' (ID: {project_id_old}) ---")

    if not old_repo_url_from_stub:
        log_status(f"WARNING: ssh_url_to_repo not found directly in project stub for {project_namespace_path_old}. Will try to construct it. This project's gitlab.rb `external_url` and `gitlab_shell_ssh_port` must be correct.")
        # If not in stub, construct it, but this relies on server config being perfect
        old_repo_url = f"ssh://git@{OLD_GITLAB_SSH_HOST}:{OLD_GITLAB_SSH_PORT}/{project_namespace_path_old}.git"
    else:
        # If the API provides it, it might have the wrong port if gitlab_shell_ssh_port is not set in gitlab.rb
        # We correct it here based on our .env config
        old_repo_url = old_repo_url_from_stub.replace(f":{gl_old.gitlab_url.split(':')[-1] if ':' in gl_old.gitlab_url else '22'}", f":{OLD_GITLAB_SSH_PORT}")


    project_payload = {
        'name': project_name_old,
        'path': project_path_old,
        'description': project_description_old,
        'visibility': project_visibility_old,
        'initialize_with_readme': False
    }
    # ... (rest of the project creation logic, using these stub attributes, is the same as before) ...
    # ... (namespace_key_for_duplicate_check, CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE, etc.) ...
    # ... (new_project creation or finding existing new_project) ...
    namespace_key_for_duplicate_check = "user_namespace_token_owner" 
    if new_target_namespace_id:
        project_payload['namespace_id'] = new_target_namespace_id
        namespace_key_for_duplicate_check = str(new_target_namespace_id)
        log_status(f"  Targeting New Mapped Group ID: {new_target_namespace_id} for project '{project_name_old}'")
    else:
        log_status(f"  Targeting user namespace of API token owner for project '{project_name_old}'.")

    if namespace_key_for_duplicate_check not in CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE:
        CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check] = set()
    
    new_project = None
    if project_path_old in CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check]:
        log_status(f"Project path '{project_path_old}' already processed for namespace '{namespace_key_for_duplicate_check}'. Finding existing.")
        try:
            if new_target_namespace_id:
                ns_obj = gl_new.groups.get(new_target_namespace_id)
                projects_in_ns = ns_obj.projects.list(search=project_path_old, all=True, lazy=True)
            else: 
                projects_in_ns = gl_new.projects.list(owned=True, search=project_path_old, all=True, lazy=True)
            found_project_lazy = next((p for p in projects_in_ns if p.path == project_path_old), None)
            if found_project_lazy: new_project = gl_new.projects.get(found_project_lazy.id)
            if not new_project: log_status(f"Could not find existing project '{project_path_old}'. Skipping."); return False
            log_status(f"Found existing project '{new_project.name}' with ID {new_project.id}.")
        except Exception as e_find: log_status(f"Error finding existing project '{project_name_old}': {e_find}. Skipping."); return False
    else:
        try:
            log_status(f"Creating project with payload: {json.dumps(project_payload)}")
            new_project = gl_new.projects.create(project_payload)
            log_status(f"Successfully created new project '{new_project.name}' (New ID: {new_project.id}).")
            CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check].add(new_project.path)
        except gitlab.exceptions.GitlabCreateError as e:
            # ... (error handling for create, including finding if "already taken") ...
            err_msg_lower = str(e.error_message).lower()
            if "has already been taken" in err_msg_lower or "path already exists" in err_msg_lower :
                CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check].add(project_path_old)
                log_status(f"Project path '{project_path_old}' resulted in 'already taken'. Retrying find.")
                try:
                    if new_target_namespace_id:
                        ns_obj = gl_new.groups.get(new_target_namespace_id)
                        projects_in_ns = ns_obj.projects.list(search=project_path_old, all=True, lazy=True)
                    else: projects_in_ns = gl_new.projects.list(owned=True, search=project_path_old, all=True, lazy=True)
                    found_project_lazy = next((p for p in projects_in_ns if p.path == project_path_old), None)
                    if found_project_lazy: new_project = gl_new.projects.get(found_project_lazy.id)
                    if not new_project: log_status(f"Still couldn't find '{project_path_old}' after 'already taken'. Skipping."); return False
                    log_status(f"Found existing project '{new_project.name}' ID {new_project.id} after 'already taken'.")
                except Exception as e_find_after_fail: log_status(f"Error finding after 'already taken' for '{project_name_old}': {e_find_after_fail}. Skipping."); return False
            else: log_status(f"ERROR creating project '{project_name_old}'. API: {e.error_message}. Resp: {e.response_body}"); return False
        except Exception as e_unexp_proj: log_status(f"UNEXPECTED ERROR creating project '{project_name_old}': {e_unexp_proj}"); return False
    
    if not new_project: log_status(f"ERROR: new_project object is None for old project '{project_name_old}'. Cannot proceed."); return False

    # --- Git Operations ---
    # Use the old_repo_url determined at the start of this function
    new_repo_url = f"ssh://git@{NEW_GITLAB_SSH_HOST}:{NEW_GITLAB_SSH_PORT}/{new_project.path_with_namespace}.git"
    log_status(f"Old Repo URL for clone: {old_repo_url}") # This was determined from stub or constructed
    log_status(f"New Repo URL for push: {new_repo_url}")

    safe_path_old = project_path_old.replace('/', '_')
    temp_repo_path = os.path.join(MIGRATION_TEMP_DIR, f"{safe_path_old}_{project_id_old}_{int(time.time() * 1000)}.git")
    if os.path.exists(temp_repo_path): shutil.rmtree(temp_repo_path)

    log_status(f"Cloning (mirror) '{old_repo_url}' to '{temp_repo_path}'...")
    # ... (rest of git clone, check for empty, git push, cleanup logic is the same as before) ...
    clone_proc = subprocess.run(['git', 'clone', '--mirror', old_repo_url, temp_repo_path], capture_output=True, text=True, check=False)
    if clone_proc.returncode != 0:
        if "empty repository" in clone_proc.stderr.lower():
            log_status(f"INFO: Old project '{project_namespace_path_old}' is empty. Repo created on new instance, skipping push.")
            shutil.rmtree(temp_repo_path, ignore_errors=True); return True 
        log_status(f"ERROR: Failed to clone '{old_repo_url}'. Stderr: {clone_proc.stderr}")
        shutil.rmtree(temp_repo_path, ignore_errors=True); return False

    log_status(f"Pushing (mirror) from '{temp_repo_path}' to new remote '{new_repo_url}'...")
    try:
        subprocess.run(['git', '--git-dir', temp_repo_path, 'remote', 'add', 'aws-target', new_repo_url], check=True, capture_output=True, text=True)
        push_proc = subprocess.run(['git', '--git-dir', temp_repo_path, 'push', '--mirror', 'aws-target'], capture_output=True, text=True, check=False)
    except subprocess.CalledProcessError as e_remote:
        log_status(f"ERROR adding remote for '{new_repo_url}'. Stderr: {e_remote.stderr}"); shutil.rmtree(temp_repo_path, ignore_errors=True); return False
    finally:
        shutil.rmtree(temp_repo_path, ignore_errors=True) # Ensure cleanup

    if push_proc.returncode != 0:
        if "deny updating a hidden ref" in push_proc.stderr or "rpc error: code = Canceled" in push_proc.stderr or "No refs in common" in push_proc.stdout:
            log_status(f"INFO/WARNING: Push to '{new_repo_url}' had non-critical messages. Stdout: {push_proc.stdout} Stderr: {push_proc.stderr}"); return True 
        log_status(f"ERROR: Failed to push (mirror) to '{new_repo_url}'. Stdout: {push_proc.stdout} Stderr: {push_proc.stderr}"); return False
    
    log_status(f"Successfully migrated Git data for '{project_namespace_path_old}'.")
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
    for old_id, new_id in OLD_TO_NEW_GROUP_ID_MAP.items(): log_status(f"  Old Group ID: {old_id} -> New Group ID: {new_id}")

    log_status("=== PHASE 2: Migrating Projects and Repositories ===")
    projects_migrated_count = 0; projects_failed_count = 0
    
    old_projects_list_full = []
    try:
        log_status("Attempting to fetch all projects from old GitLab using MANUAL pagination...")
        page = 1; per_page_projects = 20 # Keep low if old server unstable
        while True:
            log_status(f"Fetching projects page {page} (per_page={per_page_projects}) from old GitLab...")
            projects_on_page_stubs = gl_old.projects.list(page=page, per_page=per_page_projects, archived=False, statistics=False, simple=True, as_list=True, all=False) # simple=True might help
            if not projects_on_page_stubs: log_status("No more projects on this page or API error."); break
            old_projects_list_full.extend(projects_on_page_stubs)
            log_status(f"Fetched {len(projects_on_page_stubs)} project stubs on page {page}. Total stubs so far: {len(old_projects_list_full)}")
            if len(projects_on_page_stubs) < per_page_projects: log_status("Likely the last page of projects fetched."); break
            page += 1; time.sleep(0.2)
    except Exception as e:
        log_status(f"ERROR fetching project list from old GitLab: {e}. Halting project migration."); return

    log_status(f"Total project stubs fetched for processing: {len(old_projects_list_full)}.")

    for old_project_stub_data in old_projects_list_full:
        new_target_namespace_id = None
        # old_project_stub_data is now a dict-like object from the list call
        # It should have 'namespace': {'id': ..., 'kind': ...}
        namespace_info = old_project_stub_data.attributes.get('namespace', {})
        old_namespace_id = namespace_info.get('id')
        old_namespace_kind = namespace_info.get('kind')

        if old_namespace_kind == 'group':
            if old_namespace_id in OLD_TO_NEW_GROUP_ID_MAP:
                new_target_namespace_id = OLD_TO_NEW_GROUP_ID_MAP[old_namespace_id]
            else:
                log_status(f"WARNING: No new group map for old group ID {old_namespace_id} (project: {old_project_stub_data.path_with_namespace}). Skipping.")
                projects_failed_count += 1; continue
        elif old_namespace_kind == 'user':
            log_status(f"Project '{old_project_stub_data.name}' is a user project. Will create under token owner.")
        else:
            log_status(f"Unknown namespace kind '{old_namespace_kind}' for project '{old_project_stub_data.name}'. Skipping.")
            projects_failed_count +=1; continue
        
        # Pass the project stub directly to migrate_project_repo_py
        # No need for gl_old.projects.get(id) if list() provides enough info (like ssh_url_to_repo)
        if migrate_project_repo_py(old_project_stub_data, new_target_namespace_id):
            projects_migrated_count += 1
        else:
            projects_failed_count += 1
        time.sleep(0.5) 

    log_status("=== MIGRATION COMPLETE ===");
    log_status(f"Successfully migrated/processed Git data for: {projects_migrated_count} projects.")
    log_status(f"Failed to process/migrate: {projects_failed_count} projects.")

# For direct testing:
if __name__ == '__main__':
    log_status("Starting migration directly via __main__ for testing.")
    run_full_migration()
    print("\n--- Full Migration Log ---")
    for entry in migration_status_log: print(entry)