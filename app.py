from flask import Flask, render_template, request, jsonify, redirect, url_for
import migration_logic 
import threading
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24) # For session management, flash messages etc.

migration_thread = None
# This flag is specific to the Flask app's knowledge of a running task,
# distinct from migration_logic.current_migration_state["status"]
is_migration_task_active = False 

@app.route('/')
def index():
    config_display = { # Only pass non-sensitive info to template
        "OLD_GITLAB_URL": migration_logic.OLD_GITLAB_URL,
        "NEW_GITLAB_URL": migration_logic.NEW_GITLAB_URL,
        "OLD_GITLAB_SSH_HOST": migration_logic.OLD_GITLAB_SSH_HOST,
        "OLD_GITLAB_SSH_PORT": migration_logic.OLD_GITLAB_SSH_PORT,
        "NEW_GITLAB_SSH_HOST": migration_logic.NEW_GITLAB_SSH_HOST,
        "NEW_GITLAB_SSH_PORT": migration_logic.NEW_GITLAB_SSH_PORT,
    }
    # Check the actual state for initial button rendering
    with migration_logic.state_lock:
        current_status = migration_logic.current_migration_state["status"]
        initial_is_migrating = current_status in ["initializing", "migrating_groups", "migrating_projects"]

    return render_template('index.html', config=config_display, is_migrating_initial=initial_is_migrating)


@app.route('/start-migration', methods=['POST'])
def start_migration_route():
    global migration_thread, is_migration_task_active
    
    with migration_logic.state_lock:
        current_status = migration_logic.current_migration_state["status"]
        # Check both the app's flag and the detailed status
        if is_migration_task_active and migration_thread and migration_thread.is_alive():
            migration_logic._log_and_update_state("Attempt to start migration while one is already in progress.", log_type="warning", action="Migration already running")
            return jsonify({"status": "warning", "message": "Migration is already in progress."}), 200
        elif current_status in ["initializing", "migrating_groups", "migrating_projects"]:
             migration_logic._log_and_update_state("Migration appears to be in an active state. Please check status.", log_type="warning", action="Migration in active state")
             return jsonify({"status": "warning", "message": "Migration state is active. If this is an error, restart app."}), 200


    migration_logic._log_and_update_state("Received request to start migration.", action="Initiating migration", set_status="initializing")
    is_migration_task_active = True

    def migration_task_wrapper():
        global is_migration_task_active
        try:
            migration_logic.run_full_migration() 
        except Exception as e:
            migration_logic._log_and_update_state(f"CRITICAL THREAD ERROR: Migration task failed: {e}", log_type="error", error_msg=str(e), set_status="error")
        finally:
            is_migration_task_active = False 
            # The status inside current_migration_state["status"] should be 'completed' or 'error' by now
            # If it's still 'running', it means an unhandled exit, so mark as error.
            with migration_logic.state_lock:
                if migration_logic.current_migration_state["status"] not in ["completed", "error"]:
                    migration_logic.current_migration_state["status"] = "error"
                    migration_logic.current_migration_state["error_message"] = migration_logic.current_migration_state.get("error_message", "") + " Task wrapper ended unexpectedly."
            migration_logic._log_and_update_state("Migration task wrapper finished.", action="Idle")

    migration_thread = threading.Thread(target=migration_task_wrapper, daemon=True) # daemon=True so it exits if main app exits
    migration_thread.start()
    
    return jsonify({"status": "success", "message": "Migration process initiated in background."})


@app.route('/migration-status-page') 
def migration_status_page_route():
    with migration_logic.state_lock:
        state_for_template = dict(migration_logic.current_migration_state)
        state_for_template["is_migration_task_active_flask"] = is_migration_task_active # Add Flask's perspective
    return render_template('status.html', current_state=state_for_template)


@app.route('/get-status', methods=['GET'])
def get_status_json():
    with migration_logic.state_lock:
        state_copy = dict(migration_logic.current_migration_state)
        # Augment with the Flask app's knowledge if the thread is active
        state_copy["is_flask_task_active"] = is_migration_task_active 
        if is_migration_task_active and state_copy["status"] in ["idle", "completed", "error"]:
             # If flask thinks task is active, but logic state says idle/done, it means it just finished or starting
             pass # UI will handle based on state_copy["status"]
    return jsonify(state_copy)

if __name__ == '__main__':
    # use_reloader=False is important when using background threads in Flask's dev server
    # otherwise, the thread might be started twice or have issues.
    # For production, use a proper WSGI server like Gunicorn with multiple workers.
    app.run(debug=True, host='0.0.0.0', port=5001, use_reloader=False) 