# GitLab Migration Web UI Tool (Python/Flask Version)

This tool provides a web interface to manage and monitor the migration of GitLab groups, projects, and repository data from an old GitLab instance to a new one. 

**Migration Scope:**
- Group and subgroup hierarchies (including empty ones).
- Projects within their correct new groups (or under the API token owner's namespace for old user-namespace projects).
- Full Git repository data: all commits, branches, and tags (including for empty repositories).

**This script does NOT migrate:** Issues, Merge Requests, CI/CD data, full user accounts (beyond creating projects under the API token owner), most specific project/group settings, or group/project members/permissions.

---

## Table of Contents
1. [Migration Environment Overview](#migration-environment-overview)
2. [Prerequisites](#prerequisites)
   - [Migration Control Server](#1-migration-control-server-script-server)
   - [Old GitLab Instance (Source)](#2-old-gitlab-instance-source)
   - [New GitLab Instance (Target)](#3-new-gitlab-instance-target)
3. [Generating an SSH Key Pair (If Needed)](#generating-an-ssh-key-pair-if-needed)
4. [Setup on Migration Control Server](#setup-on-migration-control-server)
5. [Running the Application](#running-the-application)
6. [Using the Web UI](#using-the-web-ui)
7. [Troubleshooting Common Issues](#troubleshooting-common-issues)

---

## Migration Environment Overview

*   **Migration Control Server (Script Server):** e.g., `ip-10-0-1-97` (This is where the Python/Flask app runs, assumed as `root`).
*   **Old Local GitLab Instance (Source):**
    *   UI/API URL: `http://<OLD_GITLAB_IP>` (e.g., `http://18.61.2.115`)
    *   SSH Host: `<OLD_GITLAB_IP_FOR_SSH>`
    *   SSH Port: `<OLD_GITLAB_SSH_PORT>` (e.g., `23`)
*   **New AWS GitLab Instance (Target):**
    *   UI/API URL: `http://<NEW_GITLAB_IP>` (e.g., `http://40.192.6.189`)
    *   SSH Host: `<NEW_GITLAB_IP_FOR_SSH>`
    *   SSH Port: `<NEW_GITLAB_SSH_PORT>` (e.g., `23`)

---

## Prerequisites

### 1. Migration Control Server (e.g., `ip-10-0-1-97`)
   - Linux environment.
   - Python 3.7+ installed.
   - `pip` and `venv` installed.
   - `git` command-line tool installed and in `PATH`.
   - `curl` command-line tool installed and in `PATH`.
   - `jq` command-line JSON processor installed and in `PATH`.
   - Network access to both Old and New GitLab instances (HTTP/S for API, SSH for Git).
   - An SSH key pair for the user running this application (e.g., `/root/.ssh/id_ed25519`). **If you don't have one, see [Generating an SSH Key Pair](#generating-an-ssh-key-pair-if-needed).**
     *   The public SSH key from this pair will be referred to as `MIGRATION_SERVER_PUBLIC_KEY`.
         Example format: `ssh-ed25519 AAAA... comment`

### 2. Old GitLab Instance (Source)
   - **`external_url` Configuration (CRITICAL):**
     1.  Access its Docker container: `sudo docker exec -it <old_container_id_or_name> bash`
     2.  Edit `/etc/gitlab/gitlab.rb`.
     3.  Ensure: `external_url 'http://<OLD_GITLAB_IP>'` (uncommented, correct IP).
     4.  Ensure: `gitlab_rails['gitlab_shell_ssh_port'] = <OLD_GITLAB_SSH_PORT>` (matching configured SSH port).
     5.  Save, then run `gitlab-ctl reconfigure` (inside container).
     6.  `exit` container, then `sudo docker restart <old_container_id_or_name>`. Wait 5-10 mins.
   - **API Token (`OLD_GITLAB_TOKEN`):**
     *   A GitLab Personal Access Token with `api` scope (or at least `read_api`).
     *   This token should belong to a user with visibility to all groups/projects to be migrated (e.g., an admin or the `root` user).
   - **SSH Key Authorization:**
     *   Log into the Old GitLab UI as the user owning `OLD_GITLAB_TOKEN`.
     *   Go to Profile -> SSH Keys.
     *   Add the `MIGRATION_SERVER_PUBLIC_KEY`. Remove any other potentially conflicting keys.

### 3. New GitLab Instance (Target)
   - **`external_url` Configuration (CRITICAL):**
     1.  Access its Docker container: `sudo docker exec -it <new_container_id_or_name> bash`
     2.  Edit `/etc/gitlab/gitlab.rb`.
     3.  Ensure: `external_url 'http://<NEW_GITLAB_IP>'` (uncommented, correct IP).
     4.  Ensure: `gitlab_rails['gitlab_shell_ssh_port'] = <NEW_GITLAB_SSH_PORT>` (matching configured SSH port).
     5.  Save, then run `gitlab-ctl reconfigure` (inside container).
     6.  `exit` container, then `sudo docker restart <new_container_id_or_name>`. Wait 5-10 mins.
   - **API Token (`NEW_GITLAB_TOKEN`):**
     *   A GitLab Personal Access Token with `api` scope, belonging to an **admin user** (e.g., the `root` user). This is required for creating groups and projects.
   - **SSH Key Authorization:**
     *   Log into the New GitLab UI as the user owning `NEW_GITLAB_TOKEN`.
     *   Go to Profile -> SSH Keys.
     *   Add the `MIGRATION_SERVER_PUBLIC_KEY` (the *same* key from the Migration Control Server). Remove other keys if unsure.
   - **Optional Target Parent Group (`TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL`):** If all migrated content should go under a specific existing group on this new instance, note its numeric Group ID.

---

## Generating an SSH Key Pair (If Needed)

If the user running the script on the Migration Control Server (e.g., `root`) does not have an SSH key pair (e.g., `~/.ssh/id_ed25519`):

1.  **Log in as that user on the Migration Control Server.**
2.  **Run the key generation command:**
    ```bash
    ssh-keygen -t ed25519 -C "migration_script_user@<control_server_hostname>"
    ```
    *   When prompted `Enter file in which to save the key...`, press **Enter** to accept the default (e.g., `/root/.ssh/id_ed25519`).
    *   When prompted for a passphrase, you can press **Enter** twice for no passphrase (easier for scripts) or set one (more secure, requires `ssh-agent`).

3.  **Set Correct Permissions:**
    ```bash
    chmod 700 ~/.ssh
    chmod 600 ~/.ssh/id_ed25519  # Private key
    chmod 644 ~/.ssh/id_ed25519.pub # Public key
    ```
    (Replace `~` with `/root` if running as root and paths are absolute).

4.  **Get the Public Key Content:**
    ```bash
    cat ~/.ssh/id_ed25519.pub
    ```
    Copy the entire output (e.g., `ssh-ed25519 AAAA... comment`). This is your `MIGRATION_SERVER_PUBLIC_KEY` to be added to both GitLab instances.

---

## Setup on Migration Control Server

1.  **Place Application Files:**
    Ensure `app.py`, `migration_logic.py`, `requirements.txt`, and `static/` & `templates/` folders are in your chosen project directory (e.g., `/root/gitlab-migration-webapp/`).

2.  **Navigate to Project Directory:**
    ```bash
    cd /root/gitlab-migration-webapp
    ```

3.  **Create/Activate Python Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Create and Configure `.env` File:**
    Create `gitlab-migration-webapp/.env`. **Replace placeholders with your actual values. DO NOT commit this file with real secrets to any repository.**
    ```dotenv
    # Old LOCAL GitLab Instance
    OLD_GITLAB_URL="http://<OLD_GITLAB_IP_OR_HOSTNAME>"
    OLD_GITLAB_TOKEN="....."
    OLD_GITLAB_SSH_HOST="<OLD_GITLAB_IP_OR_HOSTNAME_FOR_SSH>"
    OLD_GITLAB_SSH_PORT="<OLD_GITLAB_SSH_HOST_PORT>" # e.g., 23

    # New AWS (or other) GitLab Instance
    NEW_GITLAB_URL="http://<NEW_GITLAB_PUBLIC_IP_OR_HOSTNAME>"
    NEW_GITLAB_TOKEN="....."
    NEW_GITLAB_SSH_HOST="<NEW_GITLAB_PUBLIC_IP_OR_HOSTNAME_FOR_SSH>"
    NEW_GITLAB_SSH_PORT="<NEW_GITLAB_SSH_HOST_PORT>" # e.g., 23

    # Optional: Target Parent Group ID on New GitLab
    # If all migrated groups/projects should go under a specific existing group on the new instance,
    # provide its numeric ID here. Otherwise, leave blank or comment out to create top-level groups.
    # TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL="" # Example: "355" 

    FLASK_APP="app.py"
    FLASK_ENV="development" # For production, use "production" and a WSGI server
    ```

6.  **Set up SSH Agent (as the user running the app, e.g., `root`):**
    ```bash
    eval "$(ssh-agent -s)"
    ssh-add /root/.ssh/id_ed25519  # Or /root/.ssh/id_rsa, ensure it's the correct private key
    ssh-add -l # Verify the correct key is loaded (check its fingerprint/comment)
    ```

7.  **Manually Accept Host Keys for Both GitLab Servers:**
    This adds the server fingerprints to `/root/.ssh/known_hosts`.
    ```bash
    ssh -p <OLD_GITLAB_SSH_PORT_FROM_ENV> git@<OLD_GITLAB_SSH_HOST_FROM_ENV> 
    # Type 'yes' if prompted. Should show "Welcome to GitLab..."

    ssh -p <NEW_GITLAB_SSH_PORT_FROM_ENV> git@<NEW_GITLAB_SSH_HOST_FROM_ENV>
    # Type 'yes' if prompted. Should show "Welcome to GitLab..."
    ```
    If "Permission denied (publickey)" occurs, re-check SSH key setup in GitLab UIs (Prerequisites I.2 and I.3).

---

## Running the Application

The application will be accessible via the IP address of your Migration Control Server on port `5001` (by default).

1.  **Activate Virtual Environment (if not already):**
    ```bash
    cd /root/gitlab-migration-webapp
    source venv/bin/activate
    ```

2.  **Start the Application using PM2 (Recommended for background running):**
    (Ensure PM2 is installed globally: `npm install pm2 -g`)
    ```bash
    pm2 start app.py --name gitlab-migration-app --interpreter venv/bin/python
    ```
    *   View logs: `pm2 logs gitlab-migration-app` (or `pm2 logs 0` if it's ID 0)
    *   Stop: `pm2 stop gitlab-migration-app`
    *   Restart: `pm2 restart gitlab-migration-app`

3.  **Access the Web UI:**
    Open your web browser and navigate to `http://<ip_of_migration_control_server>:5001`.

---

## Using the Web UI

1.  Verify displayed Source/Target GitLab URLs.
2.  Click the **"Start Full Migration"** button.
3.  Monitor "Progress Overview" and "Activity Log" sections on the page for real-time updates.
    *   **Phase 1:** Group Hierarchy Migration.
    *   **Phase 2:** Projects & Repositories Migration (listing, creating, cloning, pushing).

---

## Troubleshooting Common Issues

*   **`NameResolutionError` / `HTTPConnectionPool` errors for internal hostnames:**
    *   **Cause:** `external_url` misconfigured on the problematic GitLab instance (usually OLD one for project listing).
    *   **Fix:** Correct `external_url` in its `/etc/gitlab/gitlab.rb`, `gitlab-ctl reconfigure`, restart container.
*   **`Permission denied (publickey)` for `git clone` or `git push`:**
    *   **Cause:** Public SSH key of Migration Control Server's `root` user not correctly authorized on the target GitLab instance.
    *   **Fix:** Ensure the exact `MIGRATION_SERVER_PUBLIC_KEY` is in the GitLab UI for the API token's user. Check `ssh-agent`.
*   **"Host key verification failed" for `git clone` or `git push`:**
    *   **Cause:** Control Server hasn't accepted the GitLab SSH server's host key.
    *   **Fix:** Manually SSH (step II.7) and type `yes`.
*   **500 Internal Server Errors from OLD GitLab (often `OpenSSL::Cipher::CipherError` in GitLab logs):**
    *   **Cause:** Issue with `/etc/gitlab/gitlab-secrets.json` on OLD GitLab. Data (like runner tokens) cannot be decrypted.
    *   **Fix:** This is a server-side issue. Ideal fix: restore correct `gitlab-secrets.json`. The script uses minimal project data from `projects.list(simple=True)` to try and avoid this.
*   **Python `SyntaxError` / `AttributeError` in script logs:**
    *   Check PM2 error logs (`pm2 logs gitlab-migration-app --err`). Review the Python code.
*   **UI Not Starting/Responding:**
    *   Check PM2 logs for Flask startup errors.
    *   Check browser console (F12) for JavaScript errors (e.g., Lucide icons not loading - ensure CDN links in `index.html` are correct and accessible, or self-host the library).
*   **Projects created under wrong group or as top-level (when expecting hierarchy):**
    *   Verify `TARGET_PARENT_GROUP_ID_ON_NEW_FOR_ALL` in `.env` if using it.
    *   Check group mapping logs during Phase 1. Ensure the logic in `migrate_groups_recursive_py` correctly uses `new_parent_id_for_creation`.

---
