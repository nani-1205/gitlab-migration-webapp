from flask import Flask, render_template, request, jsonify, redirect, url_for
import migration_logic # Your migration_logic.py
import threading # For background tasks (simple version)
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24) # Needed for flash messages, etc.

# --- Global state for migration process ---
migration_thread = None
is_migrating = False


@app.route('/')
def index():
    # Pass current config to template (mask tokens in a real app)
    config = {
        "OLD_GITLAB_URL": migration_logic.OLD_GITLAB_URL,
        "NEW_GITLAB_URL": migration_logic.NEW_GITLAB_URL,
        # Add other relevant, non-sensitive config
    }
    return render_template('index.html', config=config, is_migrating=is_migrating)

@app.route('/start-migration', methods=['POST'])
def start_migration_route():
    global migration_thread, is_migrating, migration_status_log
    if is_migrating and migration_thread and migration_thread.is_alive():
        return jsonify({"status": "error", "message": "Migration already in progress."}), 400

    log_status("Received request to start migration.")
    is_migrating = True
    migration_logic.migration_status_log = [] # Clear previous log
    OLD_TO_NEW_GROUP_ID_MAP = {} # Reset map

    # Run migration in a background thread so it doesn't block the web request
    # For a production app, use Celery or RQ
    def migration_task_wrapper():
        global is_migrating
        try:
            migration_logic.run_full_migration()
        except Exception as e:
            migration_logic.log_status(f"CRITICAL THREAD ERROR: Migration task failed: {e}")
        finally:
            is_migrating = False
            migration_logic.log_status("Migration task finished (or failed critically).")

    migration_thread = threading.Thread(target=migration_task_wrapper)
    migration_thread.start()
    
    return jsonify({"status": "success", "message": "Migration process started in background. Check status page."})


@app.route('/migration-status')
def migration_status_page():
    # This would ideally fetch from a more persistent log or real-time update system
    return render_template('status.html', log_entries=migration_logic.migration_status_log, is_migrating=is_migrating)

@app.route('/get-status-log', methods=['GET'])
def get_status_log_json():
    # Simple polling endpoint for JS to get updates
    return jsonify({
        "log": migration_logic.migration_status_log, 
        "is_migrating": is_migrating
    })

def log_status(message): # Helper for app.py logging if needed
    print(f"[APP] {message}")
    migration_logic.log_status(f"[APP] {message}")


if __name__ == '__main__':
    # WARNING: This simple dev server is not for production!
    # Use a proper WSGI server like Gunicorn or Waitress for production.
    app.run(debug=True, host='0.0.0.0', port=5001) 