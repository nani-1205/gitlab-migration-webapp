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
NEW_GITLAB_TOKEN = os.getenv('NEW_GITLAB_TOKEN') # Admin token for creation
NEW_GITLAB_SSH_HOST = os.getenv('NEW_GITLAB_SSH_HOST')
NEW_GITLAB_SSH_PORT = os.getenv('NEW_GITLAB_SSH_PORT')

MIGRATION_TEMP_DIR = "./gitlab_migration_temp_python"

# --- Global state for UI updates (simplistic for example, needs robust solution) ---
migration_status_log = []
OLD_TO_NEW_GROUP_ID_MAP = {}

def log_status(message):
    print(message) # Log to console
    migration_status_log.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")
    # In a real app, this would push to a database or message queue for UI updates

# --- GitLab Clients ---
gl_old = None
gl_new = None

def initialize_gitlab_clients():
    global gl_old, gl_new
    try:
        log_status(f"Initializing old GitLab client for URL: {OLD_GITLAB_URL}")
        gl_old = gitlab.Gitlab(OLD_GITLAB_URL, private_token=OLD_GITLAB_TOKEN, timeout=30)
        gl_old.auth() # Verify authentication
        log_status("Old GitLab client authenticated.")
    except Exception as e:
        log_status(f"ERROR: Failed to initialize/authenticate old GitLab client: {e}")
        gl_old = None
        raise

    try:
        log_status(f"Initializing new GitLab client for URL: {NEW_GITLAB_URL}")
        gl_new = gitlab.Gitlab(NEW_GITLAB_URL, private_token=NEW_GITLAB_TOKEN, timeout=30)
        gl_new.auth() # Verify authentication
        log_status("New GitLab client authenticated.")
    except Exception as e:
        log_status(f"ERROR: Failed to initialize/authenticate new GitLab client: {e}")
        gl_new = None
        raise

def create_group_on_new(old_group_obj, new_parent_id=None):
    """Creates a group on the new instance based on old group data."""
    log_status(f"Attempting to create group '{old_group_obj.name}' (path: {old_group_obj.path}) on new instance.")
    payload = {
        'name': old_group_obj.name,
        'path': old_group_obj.path,
        'visibility': old_group_obj.visibility,
        'description': old_group_obj.description or ""
    }
    if new_parent_id:
        payload['parent_id'] = new_parent_id
        log_status(f"  as subgroup of new parent ID: {new_parent_id}")

    try:
        # Check if group already exists by path (if new_parent_id is None for top-level)
        # For subgroups, path uniqueness is within the parent group
        existing_groups = []
        if new_parent_id:
            try:
                parent_group = gl_new.groups.get(new_parent_id)
                existing_groups = parent_group.subgroups.list(search=old_group_obj.path, all=True)
                # Exact path match for subgroup
                exact_match = [g for g in existing_groups if g.path == old_group_obj.path]
                if exact_match:
                    existing_groups = exact_match
                else:
                    existing_groups = []

            except gitlab.exceptions.GitlabGetError:
                 log_status(f"  Parent group with ID {new_parent_id} not found on new instance.")
                 return None # Cannot create subgroup if parent not found
        else: # Top-level group
            existing_groups = gl_new.groups.list(search=old_group_obj.path, all=True)
             # Exact path match for top-level group
            exact_match = [g for g in existing_groups if g.path == old_group_obj.path]
            if exact_match:
                existing_groups = exact_match
            else:
                existing_groups = []


        if existing_groups:
            new_group = existing_groups[0]
            log_status(f"Group '{new_group.name}' (path: {new_group.path}) already exists on new instance with ID {new_group.id}. Using existing.")
            return new_group
            
        new_group = gl_new.groups.create(payload)
        log_status(f"Successfully created group '{new_group.name}' with NEW ID {new_group.id} on new instance.")
        return new_group
    except gitlab.exceptions.GitlabCreateError as e:
        log_status(f"ERROR: Failed to create group '{old_group_obj.name}' on new instance: {e.error_message}")
        if "has already been taken" in str(e.error_message): # More robust check
             log_status(f"Attempting to find existing group '{old_group_obj.name}' by path '{old_group_obj.path}' again.")
             # Try to find it again if creation failed due to it existing
             # This logic can be complex if paths are not globally unique for subgroups
             try:
                if new_parent_id:
                    parent_group = gl_new.groups.get(new_parent_id)
                    found_groups = [g for g in parent_group.subgroups.list(all=True) if g.path == old_group_obj.path]
                else:
                    found_groups = [g for g in gl_new.groups.list(all=True) if g.path == old_group_obj.path and g.parent_id is None]
                
                if found_groups:
                    log_status(f"Found existing group after create failure: ID {found_groups[0].id}")
                    return found_groups[0]
             except Exception as find_e:
                log_status(f"Error trying to find existing group after create failure: {find_e}")

        return None
    except Exception as e:
        log_status(f"UNEXPECTED ERROR during group creation for '{old_group_obj.name}': {e}")
        return None


def migrate_groups_recursive_py(old_parent_group=None, new_corresponding_parent_group_id=None):
    """Recursively migrates groups and their subgroups."""
    if not gl_old or not gl_new:
        log_status("ERROR: GitLab clients not initialized.")
        return

    if old_parent_group:
        log_status(f"Fetching subgroups for old group: '{old_parent_group.full_path}' (ID: {old_parent_group.id})")
        try:
            old_subgroups = old_parent_group.subgroups.list(all=True, as_list=True)
        except Exception as e:
            log_status(f"ERROR fetching subgroups for {old_parent_group.name}: {e}")
            return # Stop recursion for this branch if subgroups can't be fetched
    else:
        log_status("Fetching top-level groups from old instance...")
        try:
            old_subgroups = gl_old.groups.list(all=True, as_list=True, top_level_only=True)
        except Exception as e:
            log_status(f"ERROR fetching top-level groups: {e}")
            return

    if not old_subgroups:
        log_status(f"No subgroups found for old parent: {old_parent_group.name if old_parent_group else 'TOP LEVEL'}")
        return

    for old_group in old_subgroups:
        log_status(f"Processing old group: '{old_group.full_path}' (ID: {old_group.id})")
        if old_group.id in OLD_TO_NEW_GROUP_ID_MAP:
            log_status(f"Group '{old_group.name}' already processed. New ID: {OLD_TO_NEW_GROUP_ID_MAP[old_group.id]}. Checking its subgroups.")
            new_group_id = OLD_TO_NEW_GROUP_ID_MAP[old_group.id]
            # Need to get the actual group object from new GitLab to pass for subgroup recursion if we only have ID
            try:
                # new_group_obj_for_recursion = gl_new.groups.get(new_group_id) # This might not be needed if create_group_on_new passes parent ID
                migrate_groups_recursive_py(old_group, new_group_id) # Pass old_group and new_group_id
            except Exception as e:
                log_status(f"Error getting new group object for recursion: {e}")
            continue

        new_group = create_group_on_new(old_group, new_corresponding_parent_group_id)
        if new_group:
            OLD_TO_NEW_GROUP_ID_MAP[old_group.id] = new_group.id
            log_status(f"MAP: Old Group ID {old_group.id} ('{old_group.name}') -> New Group ID {new_group.id}")
            migrate_groups_recursive_py(old_group, new_group.id) # Pass old_group and new_group.id
        else:
            log_status(f"ERROR: Failed to create/map group '{old_group.name}'. Skipping its subgroups.")


def migrate_project_repo(old_project, new_namespace_id):
    """Migrates a single project's repository data."""
    if not gl_old or not gl_new:
        log_status("ERROR: GitLab clients not initialized for project migration.")
        return False

    log_status(f"--- Processing Old Project: '{old_project.path_with_namespace}' (ID: {old_project.id}) ---")

    try:
        # Check if project already exists in the target namespace with the same path
        target_namespace = None
        if new_namespace_id: # If it's a group
             try:
                target_namespace = gl_new.groups.get(new_namespace_id)
                existing_projects = target_namespace.projects.list(search=old_project.path, all=True)
                exact_match = [p for p in existing_projects if p.path == old_project.path]
                if exact_match:
                    new_project = exact_match[0]
                    log_status(f"Project '{old_project.name}' (path: {old_project.path}) already exists in new namespace ID {new_namespace_id} with ID {new_project.id}. Using existing.")
                else: # Create it
                    log_status(f"Creating project '{old_project.name}' (path: {old_project.path}) in new namespace ID {new_namespace_id}...")
                    new_project = gl_new.projects.create({
                        'name': old_project.name,
                        'path': old_project.path,
                        'namespace_id': new_namespace_id,
                        'description': old_project.description or "",
                        'visibility': old_project.visibility,
                        'initialize_with_readme': False
                    })
                    log_status(f"Successfully created new project '{new_project.name}' (ID: {new_project.id}).")
             except gitlab.exceptions.GitlabGetError:
                log_status(f"ERROR: Target namespace (group) ID {new_namespace_id} not found on new GitLab. Cannot create project '{old_project.name}'.")
                return False
        else: # User namespace project (create under token owner)
            # Check if project exists under the token owner
            # This is harder to check directly by path for user projects across all users
            # A simpler check might be just to try creating and catch the error
            log_status(f"Creating project '{old_project.name}' (path: {old_project.path}) under token owner's namespace...")
            try:
                new_project = gl_new.projects.create({
                    'name': old_project.name,
                    'path': old_project.path,
                    # No namespace_id, defaults to current user
                    'description': old_project.description or "",
                    'visibility': old_project.visibility,
                    'initialize_with_readme': False
                })
                log_status(f"Successfully created new project '{new_project.name}' (ID: {new_project.id}).")
            except gitlab.exceptions.GitlabCreateError as e_create:
                if "has already been taken" in str(e_create.error_message):
                    # Try to find it if it already exists under the user
                    try:
                        user_projects = gl_new.projects.list(owned=True, search=old_project.path, all=True)
                        exact_match = [p for p in user_projects if p.path == old_project.path]
                        if exact_match:
                            new_project = exact_match[0]
                            log_status(f"Project '{old_project.name}' already exists under token owner with ID {new_project.id}. Using existing.")
                        else:
                            log_status(f"ERROR: Failed to create project '{old_project.name}' and could not find existing: {e_create.error_message}")
                            return False
                    except Exception as e_find:
                        log_status(f"ERROR: Project creation failed ('already taken') and subsequent find also failed for '{old_project.name}': {e_find}")
                        return False
                else:
                    log_status(f"ERROR: Failed to create project '{old_project.name}': {e_create.error_message}")
                    return False


        # Determine SSH URLs (assuming gitlab.rb 'gitlab_shell_ssh_port' is set correctly)
        old_repo_url = old_project.attributes.get('ssh_url_to_repo', '').replace(f":{gl_old.gitlab_url.split(':')[-1] if ':' in gl_old.gitlab_url else '22'}", f":{OLD_GITLAB_SSH_PORT}")
        new_repo_url = new_project.attributes.get('ssh_url_to_repo', '').replace(f":{gl_new.gitlab_url.split(':')[-1] if ':' in gl_new.gitlab_url else '22'}", f":{NEW_GITLAB_SSH_PORT}")
        
        # Manual construction if API doesn't provide correct port (less ideal)
        if not old_repo_url: # Fallback if API URL is missing
            old_repo_url = f"ssh://git@{OLD_GITLAB_SSH_HOST}:{OLD_GITLAB_SSH_PORT}/{old_project.path_with_namespace}.git"
        if not new_repo_url: # Fallback
             new_repo_url = f"ssh://git@{NEW_GITLAB_SSH_HOST}:{NEW_GITLAB_SSH_PORT}/{new_project.path_with_namespace}.git"

        log_status(f"Old Repo URL for clone: {old_repo_url}")
        log_status(f"New Repo URL for push: {new_repo_url}")

        temp_repo_path = os.path.join(MIGRATION_TEMP_DIR, f"{old_project.path}_{old_project.id}.git")
        if os.path.exists(temp_repo_path):
            shutil.rmtree(temp_repo_path)

        log_status(f"Cloning (mirror) '{old_repo_url}' to '{temp_repo_path}'...")
        clone_process = subprocess.run(['git', 'clone', '--mirror', old_repo_url, temp_repo_path], capture_output=True, text=True)
        if clone_process.returncode != 0:
            log_status(f"ERROR: Failed to clone '{old_repo_url}'. Stderr: {clone_process.stderr}")
            return False
        
        # Check if repo is empty
        # A bit naive, a better check looks for actual refs other than HEAD
        refs_check_process = subprocess.run(['git', '--git-dir', temp_repo_path, 'show-ref'], capture_output=True, text=True)
        if not refs_check_process.stdout.strip() or "empty repository" in clone_process.stderr.lower():
            log_status(f"INFO: Old project '{old_project.path_with_namespace}' is empty or clone resulted in empty. Skipping push.")
            shutil.rmtree(temp_repo_path)
            return True # Consider this a success for an empty repo

        log_status(f"Pushing (mirror) from '{temp_repo_path}' to new AWS remote '{new_repo_url}'...")
        push_process = subprocess.run(['git', '--git-dir', temp_repo_path, 'push', '--mirror', new_repo_url], capture_output=True, text=True)
        
        shutil.rmtree(temp_repo_path) # Clean up

        if push_process.returncode != 0:
            # Check for common "deny updating a hidden ref" which is often okay for --mirror
            if "deny updating a hidden ref" in push_process.stderr or "rpc error: code = Canceled" in push_process.stderr:
                 log_status(f"WARNING: Push to '{new_repo_url}' had rejections for internal refs (e.g., merge-requests), but user branches/tags likely pushed. Stderr: {push_process.stderr}")
                 return True # Count as success if only hidden refs rejected
            log_status(f"ERROR: Failed to push (mirror) to '{new_repo_url}'. Stderr: {push_process.stderr}")
            return False
        
        log_status(f"Successfully migrated Git data for '{old_project.path_with_namespace}'.")
        return True

    except Exception as e:
        log_status(f"CRITICAL ERROR processing project {old_project.path_with_namespace}: {e}")
        return False


def run_full_migration():
    global migration_status_log, OLD_TO_NEW_GROUP_ID_MAP
    migration_status_log = [] # Clear log for new run
    OLD_TO_NEW_GROUP_ID_MAP = {}

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
    migrate_groups_recursive_py() # Start with top-level
    log_status("=== FINISHED PHASE 1: Group Hierarchy Migration ===")
    log_status("Final Group ID Map:")
    for old_id, new_id in OLD_TO_NEW_GROUP_ID_MAP.items():
        log_status(f"  Old Group ID: {old_id} -> New Group ID: {new_id}")

    log_status("=== PHASE 2: Migrating Projects and Repositories ===")
    migrated_project_count = 0
    failed_project_count = 0
    
    try:
        old_projects = gl_old.projects.list(all=True, as_list=True, archived=False) # Get all non-archived
    except Exception as e:
        log_status(f"ERROR: Could not fetch project list from old GitLab: {e}")
        return

    log_status(f"Found {len(old_projects)} projects to process from old instance.")

    for old_project in old_projects:
        new_namespace_id_for_project = None
        if old_project.namespace['kind'] == 'group':
            if old_project.namespace['id'] in OLD_TO_NEW_GROUP_ID_MAP:
                new_namespace_id_for_project = OLD_TO_NEW_GROUP_ID_MAP[old_project.namespace['id']]
            else:
                log_status(f"WARNING: No new group mapping found for old group ID {old_project.namespace['id']} (project: {old_project.path_with_namespace}). Skipping project.")
                failed_project_count += 1
                continue
        elif old_project.namespace['kind'] == 'user':
            # For user projects, new_namespace_id will be None, project created under token owner
             log_status(f"Project '{old_project.name}' is a user project. Will be created under token owner on new GitLab.")
        else:
            log_status(f"Unknown namespace kind for project {old_project.name}. Skipping.")
            failed_project_count +=1
            continue

        if migrate_project_repo(old_project, new_namespace_id_for_project):
            migrated_project_count += 1
        else:
            failed_project_count += 1
        time.sleep(0.2) # Be a bit nice to APIs

    log_status("=== MIGRATION COMPLETE ===")
    log_status(f"Successfully processed (cloned/pushed) repositories for: {migrated_project_count} projects.")
    log_status(f"Failed to process/migrate: {failed_project_count} projects.")

if __name__ == '__main__':
    # This is just for direct execution, Flask app will call run_full_migration differently
    # run_full_migration()
    # print("\n--- Full Migration Log ---")
    # for entry in migration_status_log:
    #     print(entry)
    pass