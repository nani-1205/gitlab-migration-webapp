from flask import Flask, render_template, request, jsonify, redirect, url_for
import migration_logic 
import threading
import os
import io
import pandas as pd
from fpdf import FPDF
from flask import send_file
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = os.urandom(24)

@app.after_request
def add_header(r):
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    return r


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
        initial_is_migrating = current_status in ["initializing", "migrating_users", "migrating_groups", "migrating_projects"]
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
            "users": {"total": 0, "completed": 0, "current_item_name": ""},
            "groups": {"total": 0, "completed": 0, "current_item_name": ""},
            "projects": {"total": 0, "completed": 0, "current_item_name": "", "failed": 0, "errors_resolved": 0},
        }
        migration_logic.OLD_TO_NEW_GROUP_ID_MAP = {}
        migration_logic.OLD_TO_NEW_USER_ID_MAP = {}
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

@app.route('/download-report/xls', methods=['GET'])
def download_report_xls():
    failed_repos = migration_logic.FAILED_REPOS
    done_repos = migration_logic.DONE_REPOS
    
    all_repos = []
    for r in done_repos:
        all_repos.append({"Repo Name": r.get("Repo Name"), "Old URL": r.get("Old URL"), "Status": "Success", "Details": "Migrated successfully"})
    for r in failed_repos:
        all_repos.append({"Repo Name": r.get("Repo Name"), "Old URL": r.get("Old URL"), "Status": "Failed", "Details": r.get("Reason", "Unknown")})
        
    if not all_repos:
        all_repos = [{"Repo Name": "None", "Old URL": "N/A", "Status": "N/A", "Details": "No migrations attempted."}]
        
    df = pd.DataFrame(all_repos)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Migration Report')
    output.seek(0)
    return send_file(output, download_name="migration_report.xlsx", as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/download-report/pdf', methods=['GET'])
def download_report_pdf():
    failed_repos = migration_logic.FAILED_REPOS
    done_repos = migration_logic.DONE_REPOS
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", style='B', size=14)
    pdf.cell(200, 10, txt="GitLab Migration Execution Report", ln=True, align='C')
    pdf.ln(5)
    
    # Successful Repos
    pdf.set_font("Arial", style='B', size=12)
    pdf.set_text_color(16, 185, 129) # Emerald green
    pdf.cell(200, 10, txt=f"Successfully Migrated Repositories ({len(done_repos)})", ln=True)
    pdf.set_text_color(0, 0, 0)
    
    if not done_repos:
        pdf.set_font("Arial", size=10)
        pdf.cell(200, 8, txt="No successful repository migrations recorded.", ln=True)
    else:
        for idx, repo in enumerate(done_repos, 1):
            pdf.set_font("Arial", style='B', size=10)
            pdf.cell(200, 6, txt=f"{idx}. {repo.get('Repo Name', 'Unknown')}", ln=True)
            pdf.set_font("Arial", size=9)
            pdf.cell(200, 5, txt=f"URL: {repo.get('Old URL', 'Unknown')}", ln=True)
            pdf.ln(3)
            
    pdf.ln(5)
    
    # Failed Repos
    pdf.set_font("Arial", style='B', size=12)
    pdf.set_text_color(239, 68, 68) # Red
    pdf.cell(200, 10, txt=f"Failed Migrations ({len(failed_repos)})", ln=True)
    pdf.set_text_color(0, 0, 0)
    
    if not failed_repos:
        pdf.set_font("Arial", size=10)
        pdf.cell(200, 8, txt="No failures recorded.", ln=True)
    else:
        for idx, repo in enumerate(failed_repos, 1):
            pdf.set_font("Arial", style='B', size=10)
            pdf.cell(200, 6, txt=f"{idx}. {repo.get('Repo Name', 'Unknown')}", ln=True)
            pdf.set_font("Arial", size=9)
            pdf.cell(200, 5, txt=f"URL: {repo.get('Old URL', 'Unknown')}", ln=True)
            pdf.multi_cell(0, 5, txt=f"Reason: {repo.get('Reason', 'Unknown')}")
            pdf.ln(3)

    output = io.BytesIO()
    output.write(pdf.output(dest='S').encode('latin-1'))
    output.seek(0)
    return send_file(output, download_name="migration_report.pdf", as_attachment=True, mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001, use_reloader=False)