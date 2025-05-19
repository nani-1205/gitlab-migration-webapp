from flask import Flask, render_template, request, jsonify, redirect, url_for
import migration_logic 
import threading
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)

migration_thread = None
is_migration_task_active_flask_flag = False # Flask app's view of an active task

@app.route('/')
def index():
    config_display = {
        "OLD_GITLAB_URL": migration_logic.OLD_GITLAB_URL,
        "NEW_GITLAB_URL": migration_logic.NEW_GITLAB_URL,
        "OLD_GITLAB_SSH_HOST": migration_logic.OLD_GITLAB_SSH_HOST,
        "OLD_GITLAB_SSH_PORT": migration_logic.OLD_GITLAB_SSH_PORT,
        "NEW_GITLAB_SSH_HOST": migration_logic.NEW_GITLAB_SSH_HOST,
        "NEW_GITLAB_SSH_PORT": migration_logic.NEW_GITLAB_SSH_PORT,
    }
    with migration_logic.state_lock:
        current_status = migration_logic.current_migration_state["status"]
        initial_is_migrating = current_status in ["initializing", "migrating_groups", "migrating_projects"]
    return render_template('index.html', config=config_display, is_migrating_initial=initial_is_migrating)


@app.route('/start-migration', methods=['POST'])
def start_migration_route():
    global migration_thread, is_migration_task_active_flask_flag
    
    with migration_logic.state_lock:
        current_detailed_status = migration_logic.current_migration_state["status"]
    
    if is_migration_task_active_flask_flag and migration_thread and migration_thread.is_alive():
        migration_logic._log_and_update_state("Attempt to start migration while task is already active.", log_type="warning", action="Migration already running")
        return jsonify({"status": "warning", "message": "Migration is already in progress."}), 200
    
    # Reset for a new run
    with migration_logic.state_lock:
        migration_logic.current_migration_state["status"] = "initializing"
        migration_logic.current_migration_state["logs"] = []
        migration_logic.current_migration_state["error_message"] = None
        migration_logic.current_migration_state["stats"] = {
            "groups": {"total": 0, "completed": 0, "current_item_name": ""},
            "projects": {"total": 0, "completed": 0, "current_item_name": ""},
        }
        migration_logic.OLD_TO_NEW_GROUP_ID_MAP = {}
        migration_logic.CREATED_PROJECT_PATHS_IN_NEW_NAMESPACE = {}

    migration_logic._log_and_update_state("Received request to start migration.", action="Initiating migration", set_status="initializing")
    is_migration_task_active_flask_flag = True

    def migration_task_wrapper():
        global is_migration_task_active_flask_flag
        try:
            migration_logic.run_full_migration() 
        except Exception as e:
            migration_logic._log_and_update_state(f"CRITICAL THREAD ERROR: Migration task failed: {e}", log_type="error", error_msg=str(e), set_status="error")
        finally:
            is_migration_task_active_flask_flag = False 
            with migration_logic.state_lock:
                if migration_logic.current_migration_state["status"] not in ["completed", "error"]:
                    migration_logic.current_migration_state["status"] = "error"
                    migration_logic.current_migration_state["error_message"] = (migration_logic.current_migration_state.get("error_message","") + " Task wrapper ended unexpectedly.").strip()
            migration_logic._log_and_update_state("Migration task wrapper finished.", action="Idle")

    migration_thread = threading.Thread(target=migration_task_wrapper, daemon=True)
    migration_thread.start()
    
    return jsonify({"status": "success", "message": "Migration process initiated in background."})

@app.route('/get-status', methods=['GET'])
def get_status_json():
    with migration_logic.state_lock:
        state_copy = dict(migration_logic.current_migration_state)
    return jsonify(state_copy)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001, use_reloader=False)