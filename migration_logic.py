import gitlab
import os
import subprocess
import shutil
import time
from dotenv import load_dotenv
import json
import threading
import re # For parsing SSH URLs if needed

load_dotenv()

# --- Configuration ---
OLD_GITLAB_URL = os.getenv('OLD_GITLAB_URL')
OLD_GITLAB_TOKEN = os.getenv('OLD_GITLAB_TOKEN')
OLD_GITLAB_SSH_HOST = os.getenv('OLD_GITLAB_SSH_HOST')
OLD_GITLAB_SSH_PORT = os.getenv('OLD_GITLAB_SSH_PORT')

NEW_GITLAB_URL = os.getenv('NEW_GITLAB_URL')
NEW_GITLAB_TOKEN = os.getenv('NEW_GITLAB_TOKEN')
NEW_GITLAB_SSH_HOST = os.getenv('NEW_GITLAB_SSH_HOST')
NEW_GITLAB_SSH_PORT = os.getenv('NEW_GITLAB_SSH_PORT')

TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL_STR = os.getenv('TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL', None)
TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = None
if TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL_STR:
    try:
        TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL = int(TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL_STR)
    except (ValueError, TypeError):
        print(f"WARNING: TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL ('{TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL_STR}') not valid. Groups will be created at top level.")

MIGRATION_TEMP_DIR = "./gitlab_migration_temp_python_v7" # Updated version

# --- Global State ---
current_migration_state = {
    "status": "idle",
    "current_action": "Waiting to start...",
    "stats": {
        "groups": {"total": 0, "completed": 0, "current_item_name": ""},
        "projects": {"total": 0, "completed": 0, "current_item_name": ""},
    },
    "logs": [],
    "error_message": None
}
state_lock = threading.Lock()

gl_old = None
gl_new = None

# --- Logging and State Update ---
def _log_and_update_state(message, log_type="info", action=None, section=None, item_name=None, increment_completed=False, error_msg=None, set_status=None):
    global current_migration_state
    with state_lock:
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        full_message = f"[{timestamp}] [{log_type.upper()}] {message}"
        print(full_message)
        current_migration_state["logs"].insert(0, {"id": time.time(), "timestamp": timestamp, "message": message, "type": log_type})
        current_migration_state["logs"] = current_migration_state["logs"][:200]

        if action: current_migration_state["current_action"] = action
        if section and item_name: current_migration_state["stats"][section]["current_item_name"] = item_name
        if section and increment_completed: current_migration_state["stats"][section]["completed"] += 1
        if error_msg: current_migration_state["error_message"] = error_msg
        if set_status: current_migration_state["status"] = set_status


# --- GitLab Client Initialization ---
def initialize_gitlab_clients():
    global gl_old, gl_new
    _log_and_update_state("Initializing GitLab Clients...", action="Initializing clients", set_status="initializing")
    try:
        _log_and_update_state(f"Old GitLab Client: URL={OLD_GITLAB_URL}", action="Connecting to Old GitLab")
        gl_old = gitlab.Gitlab(OLD_GITLAB_URL, private_token=OLD_GITLAB_TOKEN, timeout=60, keep_base_url=True)
        gl_old.auth()
        _log_and_update_state("Old GitLab client authenticated successfully.")
    except Exception as e:
        _log_and_update_state(f"Failed to init old GitLab client: {e}", log_type="error", error_msg=str(e), set_status="error")
        gl_old = None; raise
    try:
        _log_and_update_state(f"New GitLab Client: URL={NEW_GITLAB_URL}", action="Connecting to New GitLab")
        gl_new = gitlab.Gitlab(NEW_GITLAB_URL, private_token=NEW_GITLAB_TOKEN, timeout=60, keep_base_url=True)
        gl_new.auth()
        _log_and_update_state("New GitLab client authenticated successfully.")
    except Exception as e:
        _log_and_update_state(f"Failed to init new GitLab client: {e}", log_type="error", error_msg=str(e), set_status="error")
        gl_new = None; raise
    _log_and_update_state("GitLab Clients Initialized.", action="Clients Ready")

# --- Group Migration Logic ---
def get_full_group_object(gl_instance, group_id_or_lazy_obj, context="old"):
    # ... (Same as v6 - ensure internal _log_and_update_state calls are minimal or specific) ...
    if not gl_instance: return None
    try:
        group_id = group_id_or_lazy_obj.id if hasattr(group_id_or_lazy_obj, 'id') else group_id_or_lazy_obj
        return gl_instance.groups.get(group_id)
    except Exception as e:
        _log_and_update_state(f"Could not get full group object for {context}_id {group_id}: {e}", log_type="warning")
        return None

def create_or_find_group_on_new(old_group_obj_full, new_parent_id_for_creation=None):
    # ... (Same as v6, ensure internal _log_and_update_state calls make sense) ...
    name = old_group_obj_full.name; path_slug = old_group_obj_full.path
    visibility = old_group_obj_full.visibility; description = old_group_obj_full.description or ""
    _log_and_update_state(f"Group: '{name}' (Path: {path_slug})", action=f"Processing Group: {name}", section="groups", item_name=name)
    if new_parent_id_for_creation: _log_and_update_state(f"  Targeting new parent group ID: {new_parent_id_for_creation}")
    try: # Attempt to find existing group first
        candidate_groups = []
        if new_parent_id_for_creation:
            try:
                parent_group_new = gl_new.groups.get(new_parent_id_for_creation)
                all_subgroups = parent_group_new.subgroups.list(all=True) # Get all, then filter
                candidate_groups = [sg for sg in all_subgroups if sg.path == path_slug]
            except gitlab.exceptions.GitlabGetError: _log_and_update_state(f"ERROR: New parent ID {new_parent_id_for_creation} not found. Cannot create '{name}'.", log_type="error"); return None
        else: 
            groups_from_search = gl_new.groups.list(search=path_slug, all=True) # Search can be fuzzy
            candidate_groups = [g for g in groups_from_search if g.path == path_slug and g.parent_id is None]
        if candidate_groups:
            existing_group = gl_new.groups.get(candidate_groups[0].id) # Get full object
            _log_and_update_state(f"Group '{existing_group.name}' (Path: {existing_group.path}) already exists with NEW ID {existing_group.id}. Using it.")
            return existing_group
    except Exception as e_check: _log_and_update_state(f"Warning: Error during pre-check for group '{name}': {e_check}. Proceeding to create.", log_type="warning")
    
    payload = {'name': name, 'path': path_slug, 'visibility': visibility, 'description': description}
    if new_parent_id_for_creation: payload['parent_id'] = new_parent_id_for_creation
    try:
        _log_and_update_state(f"Creating group with payload: {json.dumps(payload)}")
        new_group = gl_new.groups.create(payload)
        _log_and_update_state(f"Successfully created group '{new_group.name}' with NEW ID {new_group.id}.")
        return new_group
    except gitlab.exceptions.GitlabCreateError as e:
        _log_and_update_state(f"ERROR creating group '{name}'. API: {e.error_message}. Resp: {e.response_body}", log_type="error")
        if "has already been taken" in str(e.error_message).lower() or "path already exists" in str(e.error_message).lower():
             _log_and_update_state(f"  Retrying find for group '{path_slug}' after 'already taken' error.")
             try: # Retry find logic
                if new_parent_id_for_creation:
                    parent_group_new = gl_new.groups.get(new_parent_id_for_creation)
                    all_subgroups = parent_group_new.subgroups.list(all=True)
                    found_groups = [sg for sg in all_subgroups if sg.path == path_slug]
                else:
                    all_groups = gl_new.groups.list(all=True)
                    found_groups = [g for g in all_groups if g.path == path_slug and g.parent_id is None]
                if found_groups: _log_and_update_state(f"Found existing group '{found_groups[0].name}' ID {found_groups[0].id} on retry."); return gl_new.groups.get(found_groups[0].id)
             except Exception as e_retry_find: _log_and_update_state(f"  Retry find also failed: {e_retry_find}", log_type="warning")
        return None
    except Exception as e_unexp: _log_and_update_state(f"UNEXPECTED ERROR creating group '{name}': {e_unexp}", log_type="error"); return None

def migrate_groups_recursive_py(old_parent_group_id_for_subgroup_listing=None, new_parent_id_for_creation=None):
    # ... (Same as v6 - ensure internal _log_and_update_state calls make sense) ...
    if not gl_old or not gl_new: return
    page = 1; per_page = 100
    # Removed the top-level log from here, will be called by run_full_migration
    while True:
        old_subgroups_page_lazy = []
        try:
            if old_parent_group_id_for_subgroup_listing:
                parent_obj_old = get_full_group_object(gl_old, old_parent_group_id_for_subgroup_listing, "old parent")
                if not parent_obj_old: break
                _log_and_update_state(f"Fetching subgroups for old group: '{parent_obj_old.full_path}' (ID: {old_parent_group_id_for_subgroup_listing}), page {page}", action=f"Listing subgroups of {parent_obj_old.name}")
                old_subgroups_page_lazy = parent_obj_old.subgroups.list(page=page, per_page=per_page, as_list=False)
            else:
                _log_and_update_state(f"Fetching top-level groups from old instance, page {page}", action="Listing top-level groups")
                old_subgroups_page_lazy = gl_old.groups.list(page=page, per_page=per_page, as_list=False, top_level_only=True)
        except Exception as e: _log_and_update_state(f"ERROR fetching groups/subgroups for old_parent_id '{old_parent_group_id_for_subgroup_listing}': {e}", log_type="error"); break
        
        processed_on_page = 0
        for old_group_lazy_item in old_subgroups_page_lazy:
            processed_on_page += 1
            old_group_full = get_full_group_object(gl_old, old_group_lazy_item.id, "old current")
            if not old_group_full: _log_and_update_state(f"Could not get full object for old group ID {old_group_lazy_item.id}. Skipping.", log_type="warning"); continue
            
            # Update current item being processed for the 'groups' section
            _log_and_update_state(f"Processing old group: '{old_group_full.full_path}' (Old ID: {old_group_full.id})",
                                  section="groups", item_name=old_group_full.full_path)

            if old_group_full.id in OLD_TO_NEW_GROUP_ID_MAP:
                new_gid_for_children = OLD_TO_NEW_GROUP_ID_MAP[old_group_full.id]
                _log_and_update_state(f"  Group '{old_group_full.name}' already mapped: Old {old_group_full.id} -> New {new_gid_for_children}. Recursively checking its subgroups.")
                _log_and_update_state("", section="groups", increment_completed=True) # Count as completed
                migrate_groups_recursive_py(old_group_full.id, new_gid_for_children); continue

            new_created_group_obj = create_or_find_group_on_new(old_group_full, new_parent_id_for_creation)
            if new_created_group_obj:
                OLD_TO_NEW_GROUP_ID_MAP[old_group_full.id] = new_created_group_obj.id
                _log_and_update_state(f"  MAP: Old Group ID {old_group_full.id} ('{old_group_full.name}') -> New Group ID {new_created_group_obj.id}",
                                      section="groups", increment_completed=True)
                migrate_groups_recursive_py(old_group_full.id, new_created_group_obj.id)
            else: _log_and_update_state(f"  ERROR: Failed to create/map group '{old_group_full.name}'. Skipping its subgroups.", log_type="error")
        
        if processed_on_page == 0 and page > 1 : _log_and_update_state(f"No items processed on page {page} for old parent ID '{old_parent_group_id_for_subgroup_listing or 'TOP_LEVEL'}'. Assuming end."); break
        if processed_on_page < per_page : _log_and_update_state(f"Processed {processed_on_page} items on page {page} (less than per_page). End for old parent ID '{old_parent_group_id_for_subgroup_listing or 'TOP_LEVEL'}'."); break
        page += 1; time.sleep(0.1)


def migrate_project_repo_py(
    project_id_old, project_name_old, project_path_old, project_namespace_path_old,
    project_description_old, project_visibility_old, old_repo_ssh_url_from_stub, 
    new_target_namespace_id 
):
    # ... (Same as v6, but ensure internal _log_and_update_state calls are relevant and specific) ...
    # Example of updating state during project processing:
    _log_and_update_state(f"Project: '{project_namespace_path_old}'",
                          action=f"Processing Project: {project_name_old}",
                          section="projects", item_name=project_namespace_path_old)

    if not old_repo_ssh_url_from_stub:
        _log_and_update_state(f"CRITICAL ERROR: ssh_url_to_repo from stub is missing for project {project_namespace_path_old} (ID: {project_id_old}). Cannot clone. Skipping.", log_type="error")
        return False
    
    old_repo_url = f"ssh://git@{OLD_GITLAB_SSH_HOST}:{OLD_GITLAB_SSH_PORT}/{project_namespace_path_old}.git"
    # ... (rest of the project creation logic from v6)
    # ... (When project creation is successful: )
    # _log_and_update_state(f"Successfully created new project '{new_project.name}' ...")
    # ... (When git clone is successful: )
    # _log_and_update_state(f"Successfully cloned '{old_repo_url}'...")
    # ... (When git push is successful: )
    # _log_and_update_state(f"Successfully migrated Git data for '{project_namespace_path_old}'.", section="projects", increment_completed=True)
    # --- This function is long, so for brevity, integrate the _log_and_update_state calls ---
    # --- The logic from v6 for this function is mostly sound, just needs the state updates ---
    global CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE, gl_new # gl_old not needed if we only use stub
    
    project_payload = {
        'name': project_name_old, 'path': project_path_old,
        'description': project_description_old or "",
        'visibility': project_visibility_old or 'private',
        'initialize_with_readme': False
    }
    namespace_key_for_duplicate_check = "user_namespace_token_owner"
    if new_target_namespace_id:
        project_payload['namespace_id'] = new_target_namespace_id
        namespace_key_for_duplicate_check = str(new_target_namespace_id)
    
    if namespace_key_for_duplicate_check not in CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE:
        CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check] = set()
    
    new_project = None
    # ... (Create or Find Project Logic - from v6) ...
    if project_path_old in CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check]:
        _log_and_update_state(f"Project path '{project_path_old}' marked as processed. Finding existing.", action=f"Find Project: {project_name_old}")
        try: 
            if new_target_namespace_id:
                ns_obj = gl_new.groups.get(new_target_namespace_id)
                projects_in_ns = ns_obj.projects.list(search=project_path_old, all=True, lazy=True)
            else: projects_in_ns = gl_new.projects.list(owned=True, search=project_path_old, all=True, lazy=True)
            found_project_lazy = next((p for p in projects_in_ns if p.path == project_path_old), None)
            if found_project_lazy: new_project = gl_new.projects.get(found_project_lazy.id)
            if not new_project: _log_and_update_state(f"Could not find existing project '{project_path_old}'. Skipping.", log_type="error"); return False
            _log_and_update_state(f"Found existing project '{new_project.name}' with ID {new_project.id}.")
        except Exception as e_find: _log_and_update_state(f"Error finding existing project '{project_name_old}': {e_find}. Skipping.", log_type="error"); return False
    else: 
        try:
            _log_and_update_state(f"Creating project with payload: {json.dumps(project_payload)}", action=f"Create Project: {project_name_old}")
            new_project = gl_new.projects.create(project_payload)
            _log_and_update_state(f"Successfully created new project '{new_project.name}' (New ID: {new_project.id}).")
            CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check].add(new_project.path)
        except gitlab.exceptions.GitlabCreateError as e:
            err_msg_lower = str(e.error_message).lower() if e.error_message else ""
            if "has already been taken" in err_msg_lower or "path already exists" in err_msg_lower:
                CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE[namespace_key_for_duplicate_check].add(project_path_old)
                _log_and_update_state(f"Project path '{project_path_old}' 'already taken'. Retrying find.", log_type="warning")
                try: 
                    if new_target_namespace_id:
                        ns_obj = gl_new.groups.get(new_target_namespace_id)
                        projects_in_ns = ns_obj.projects.list(search=project_path_old, all=True, lazy=True)
                    else: projects_in_ns = gl_new.projects.list(owned=True, search=project_path_old, all=True, lazy=True)
                    found_project_lazy = next((p for p in projects_in_ns if p.path == project_path_old), None)
                    if found_project_lazy: new_project = gl_new.projects.get(found_project_lazy.id)
                    if not new_project: _log_and_update_state(f"Still couldn't find '{project_path_old}' after 'already taken'. Skipping.", log_type="error"); return False
                    _log_and_update_state(f"Found existing project '{new_project.name}' ID {new_project.id} after 'already taken'.")
                except Exception as e_find_fail: _log_and_update_state(f"Error finding after 'already taken' for '{project_name_old}': {e_find_fail}. Skipping.", log_type="error"); return False
            else: _log_and_update_state(f"ERROR creating project '{project_name_old}'. API: {e.error_message}. Resp: {e.response_body}", log_type="error"); return False
        except Exception as e_unexp_proj: _log_and_update_state(f"UNEXPECTED ERROR creating project '{project_name_old}': {e_unexp_proj}", log_type="error"); return False

    if not new_project: _log_and_update_state(f"ERROR: new_project is None for old project '{project_name_old}'. Cannot proceed.", log_type="error"); return False

    new_repo_url = f"ssh://git@{NEW_GITLAB_SSH_HOST}:{NEW_GITLAB_SSH_PORT}/{new_project.path_with_namespace}.git"
    _log_and_update_state(f"Old Repo URL for clone (final): {old_repo_url}", action=f"Cloning: {project_name_old}")
    _log_and_update_state(f"New Repo URL for push (final): {new_repo_url}")
    safe_path_old = project_path_old.replace('/', '_')
    temp_repo_path = os.path.join(MIGRATION_TEMP_DIR, f"{safe_path_old}_{project_id_old}_{int(time.time() * 1000)}.git")
    if os.path.exists(temp_repo_path): shutil.rmtree(temp_repo_path)

    _log_and_update_state(f"Cloning (mirror) '{old_repo_url}' to '{temp_repo_path}'...")
    clone_proc = subprocess.run(['git', 'clone', '--mirror', old_repo_url, temp_repo_path], capture_output=True, text=True, check=False)
    if clone_proc.returncode != 0:
        if "empty repository" in clone_proc.stderr.lower():
            _log_and_update_state(f"INFO: Old project '{project_namespace_path_old}' is empty. Repo created on new, skipping push.")
            shutil.rmtree(temp_repo_path, ignore_errors=True); return True 
        _log_and_update_state(f"ERROR: Failed to clone '{old_repo_url}'. Stderr: {clone_proc.stderr}", log_type="error")
        shutil.rmtree(temp_repo_path, ignore_errors=True); return False
    
    _log_and_update_state(f"Pushing (mirror) from '{temp_repo_path}' to new remote '{new_repo_url}'...", action=f"Pushing: {project_name_old}")
    try:
        subprocess.run(['git', '--git-dir', temp_repo_path, 'remote', 'add', 'aws-target', new_repo_url], check=True, capture_output=True, text=True)
        push_proc = subprocess.run(['git', '--git-dir', temp_repo_path, 'push', '--mirror', 'aws-target'], capture_output=True, text=True, check=False)
    except subprocess.CalledProcessError as e_remote:
        _log_and_update_state(f"ERROR adding remote for '{new_repo_url}'. Stderr: {e_remote.stderr}", log_type="error"); shutil.rmtree(temp_repo_path, ignore_errors=True); return False
    finally:
        shutil.rmtree(temp_repo_path, ignore_errors=True)

    if push_proc.returncode != 0:
        if "deny updating a hidden ref" in push_proc.stderr or "rpc error: code = Canceled" in push_proc.stderr or "No refs in common" in push_proc.stdout.strip() or "remote end hung up unexpectedly" in push_proc.stderr:
            _log_and_update_state(f"Push to '{new_repo_url}' non-critical messages or empty repo. Stdout: {push_proc.stdout.strip()} Stderr: {push_proc.stderr.strip()}", log_type="warning"); return True 
        _log_and_update_state(f"ERROR: Failed to push to '{new_repo_url}'. Stdout: {push_proc.stdout.strip()} Stderr: {push_proc.stderr.strip()}", log_type="error"); return False
    _log_and_update_state(f"Successfully migrated Git data for '{project_namespace_path_old}'.")
    return True


def run_full_migration():
    global migration_status_log, OLD_TO_NEW_GROUP_ID_MAP, CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE, current_migration_state
    # Reset state at the beginning of a run
    with state_lock:
        current_migration_state["status"] = "initializing"
        current_migration_state["logs"] = []
        current_migration_state["error_message"] = None
        current_migration_state["stats"] = {
            "groups": {"total": 0, "completed": 0, "current_item_name": ""},
            "projects": {"total": 0, "completed": 0, "current_item_name": ""},
        }
    OLD_TO_NEW_GROUP_ID_MAP = {}
    CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE = {}

    try: initialize_gitlab_clients()
    except Exception as e: _log_and_update_state(f"Halting: client init failure: {e}", log_type="error", error_msg=str(e), set_status="error"); return

    if os.path.exists(MIGRATION_TEMP_DIR): _log_and_update_state(f"Cleaning old temp dir: {MIGRATION_TEMP_DIR}"); shutil.rmtree(MIGRATION_TEMP_DIR)
    os.makedirs(MIGRATION_TEMP_DIR, exist_ok=True)

    # --- Estimate Totals for UI ---
    try:
        _log_and_update_state("Estimating total groups from old GitLab...", action="Estimating groups")
        all_old_groups_paginated = gl_old.groups.list(all=True, as_list=False, per_page=1) # Just to get total
        with state_lock: current_migration_state["stats"]["groups"]["total"] = all_old_groups_paginated.total_items if hasattr(all_old_groups_paginated, 'total_items') else 0
        _log_and_update_state(f"Estimated total groups: {current_migration_state['stats']['groups']['total']}")
    except Exception as e: _log_and_update_state(f"Warning: Could not estimate total groups: {e}", log_type="warning")

    try:
        _log_and_update_state("Estimating total projects from old GitLab...", action="Estimating projects")
        all_old_projects_paginated = gl_old.projects.list(all=True, archived=False, as_list=False, per_page=1)
        project_total_count = all_old_projects_paginated.total_items if hasattr(all_old_projects_paginated, 'total_items') else 0
        with state_lock: current_migration_state["stats"]["projects"]["total"] = project_total_count
        _log_and_update_state(f"Estimated total projects: {project_total_count}")
    except Exception as e: _log_and_update_state(f"Warning: Could not estimate total projects: {e}", log_type="warning")

    # --- Phase 1: Group Migration ---
    with state_lock: current_migration_state["status"] = "migrating_groups"
    _log_and_update_state("=== PHASE 1: Migrating Group Hierarchy ===", action="Starting group migration")
    initial_new_parent_id = TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL if TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL else None
    if initial_new_parent_id: _log_and_update_state(f"All migrated groups will be under pre-existing new group ID: {initial_new_parent_id}")
    migrate_groups_recursive_py(None, initial_new_parent_id)
    _log_and_update_state("=== FINISHED PHASE 1: Group Hierarchy Migration ===", action="Group migration complete")

    # --- Phase 2: Project and Repo Migration ---
    with state_lock: current_migration_state["status"] = "migrating_projects"
    _log_and_update_state("=== PHASE 2: Migrating Projects and Repositories ===", action="Starting project migration")
    projects_migrated_ok_count = 0; projects_failed_processing_count = 0
    old_projects_stubs_list = []
    try:
        _log_and_update_state("Fetching all project stubs from old GitLab (manual pagination)...", action="Listing old projects")
        page = 1; per_page_projects = 20 
        while True:
            _log_and_update_state(f"Fetching projects page {page} (per_page={per_page_projects})...", action=f"Listing projects (Page {page})")
            projects_on_page = gl_old.projects.list(page=page, per_page=per_page_projects, archived=False, statistics=False, simple=True, as_list=True, all=False)
            if not projects_on_page: _log_and_update_state("No more project stubs on this page or API error."); break
            old_projects_stubs_list.extend(projects_on_page)
            _log_and_update_state(f"Fetched {len(projects_on_page)} project stubs on page {page}. Total stubs: {len(old_projects_stubs_list)}")
            if len(projects_on_page) < per_page_projects: _log_and_update_state("Likely the last page of project stubs."); break
            page += 1; time.sleep(0.2)
    except Exception as e: _log_and_update_state(f"ERROR fetching project stubs: {e}. Halting.", log_type="error", error_msg=str(e), set_status="error"); return
    
    with state_lock: # Update total if initial estimation failed but list succeeded
        if current_migration_state["stats"]["projects"]["total"] == 0:
            current_migration_state["stats"]["projects"]["total"] = len(old_projects_stubs_list)
    _log_and_update_state(f"Total project stubs fetched for processing: {len(old_projects_stubs_list)}.")

    for i, old_project_stub in enumerate(old_projects_stubs_list):
        with state_lock: current_migration_state["current_action"] = f"Processing project {i+1}/{len(old_projects_stubs_list)}: {old_project_stub.name}"
        try:
            project_id_old = old_project_stub.id
            project_name_old = old_project_stub.name
            project_path_old = old_project_stub.path
            project_namespace_path_old = old_project_stub.path_with_namespace
            project_description_old = old_project_stub.attributes.get('description', "") or ""
            project_visibility_old = old_project_stub.attributes.get('visibility', 'private') or 'private'
            old_repo_ssh_url_from_stub = old_project_stub.attributes.get('ssh_url_to_repo')

            namespace_info = old_project_stub.attributes.get('namespace', {})
            old_namespace_id = namespace_info.get('id')
            old_namespace_kind = namespace_info.get('kind')
            new_target_namespace_id = None

            if old_namespace_kind == 'group':
                if old_namespace_id in OLD_TO_NEW_GROUP_ID_MAP:
                    new_target_namespace_id = OLD_TO_NEW_GROUP_ID_MAP[old_namespace_id]
                else: _log_and_update_state(f"WARNING: No new group map for old group ID {old_namespace_id} (project: {project_namespace_path_old}). Skipping.", log_type="warning"); projects_failed_processing_count += 1; continue
            elif old_namespace_kind == 'user': _log_and_update_state(f"Project '{project_name_old}' is user project. Will create under token owner.")
            else: _log_and_update_state(f"Unknown namespace kind '{old_namespace_kind}' for '{project_name_old}'. Skipping.", log_type="warning"); projects_failed_processing_count +=1; continue
            
            if migrate_project_repo_py(project_id_old, project_name_old, project_path_old, project_namespace_path_old, 
                                       project_description_old, project_visibility_old, old_repo_ssh_url_from_stub, 
                                       new_target_namespace_id):
                projects_migrated_ok_count += 1
                _log_and_update_state(f"Project {project_name_old} migrated.", section="projects", increment_completed=True)
            else:
                projects_failed_processing_count += 1
            time.sleep(0.5)
        except AttributeError as ae:
            _log_and_update_state(f"ATTRIBUTE ERROR processing stub ID {old_project_stub.id if old_project_stub else 'N/A'}: {ae}", log_type="error", error_msg=str(ae))
            _log_and_update_state(f"  Problematic stub: {old_project_stub.attributes if old_project_stub else 'N/A'}")
            projects_failed_processing_count += 1
        except Exception as e_proj_loop:
            _log_and_update_state(f"UNEXPECTED ERROR in project loop for old ID {old_project_stub.id if old_project_stub else 'N/A'}: {e_proj_loop}", log_type="error", error_msg=str(e_proj_loop))
            projects_failed_processing_count += 1

    _log_and_update_state("=== MIGRATION COMPLETE ===", action="Migration finished", set_status="completed");
    _log_and_update_state(f"Successfully processed Git data for: {projects_migrated_ok_count} projects.")
    _log_and_update_state(f"Failed to process/migrate: {projects_failed_processing_count} projects.")

if __name__ == '__main__':
    _log_and_update_state("Starting migration directly via __main__ for testing.")
    run_full_migration()