document.addEventListener('DOMContentLoaded', function() {
    // --- DOM Elements ---
    const migrationForm = document.getElementById('migrationForm');
    const liveLogArea = document.getElementById('liveLog');
    const startMigrationButton = document.getElementById('startMigrationButton'); // Specific button
    const viewStatusButton = document.getElementById('viewStatusButton');
    const clearLogButton = document.getElementById('clearLogButton');
    const migrationStateElement = document.getElementById('migrationState');

    // --- State & Configuration ---
    let pollingInterval;
    const pollingTime = 5000; // Poll every 5 seconds

    // URLs for Flask routes (these are relative paths, Flask handles the full URL)
    const startMigrationUrl = "/start-migration"; 
    const getStatusLogUrl = "/get-status-log";

    // --- Event Listeners ---
    if (migrationForm && startMigrationButton) {
        migrationForm.addEventListener('submit', function(event) {
            event.preventDefault(); // Prevent default form submission
            
            startMigrationButton.disabled = true;
            startMigrationButton.textContent = 'Starting Migration...';
            if (migrationStateElement) migrationStateElement.textContent = 'Status: Initiating...';

            fetch(startMigrationUrl, { method: 'POST' })
                .then(response => {
                    if (!response.ok) {
                        // Try to get more specific error from JSON response if available
                        return response.json().then(errData => {
                            throw new Error(errData.message || `HTTP error ${response.status}`);
                        }).catch(() => { // Fallback if no JSON in error
                            throw new Error(`HTTP error ${response.status}`);
                        });
                    }
                    return response.json();
                })
                .then(data => {
                    alert(data.message || "Migration request sent to server.");
                    if (data.status === 'success') {
                        startMigrationButton.textContent = 'Migration in Progress...';
                        if (migrationStateElement) migrationStateElement.textContent = 'Status: Migrating...';
                        pollStatus(); // Start polling for log updates
                    } else {
                        // If server indicates start failure (e.g., already running)
                        startMigrationButton.disabled = false;
                        startMigrationButton.textContent = 'Start Full Migration (Groups, Projects, Repos)';
                        if (migrationStateElement) migrationStateElement.textContent = `Status: Idle (Start failed: ${data.message || ''})`;
                    }
                })
                .catch(error => {
                    console.error('Error starting migration:', error);
                    alert('Error starting migration: ' + error.message);
                    startMigrationButton.disabled = false;
                    startMigrationButton.textContent = 'Start Full Migration (Error - Retry?)';
                    if (migrationStateElement) migrationStateElement.textContent = 'Status: Error starting migration.';
                });
        });
    }

    if (clearLogButton && liveLogArea) {
        clearLogButton.addEventListener('click', function() {
            liveLogArea.textContent = '[Client-side log display cleared]\n';
            // Note: This only clears the display in *this* browser window.
            // It doesn't affect the server-side log or other connected clients.
            // Re-fetch immediately to show current server state if desired,
            // or just let the next poll update it.
            // For now, we'll let the poll handle it or a manual refresh of status page.
        });
    }

    // --- Core Functions ---
    function fetchLog() {
        if (!liveLogArea && !migrationButton && !migrationStateElement) {
            // If essential elements are missing, don't try to fetch
            // This might happen if this script is loaded on a page without these elements
            if (pollingInterval) clearInterval(pollingInterval);
            return;
        }

        fetch(getStatusLogUrl)
            .then(response => {
                if (!response.ok) {
                    return response.json().then(errData => {
                        throw new Error(errData.message || `HTTP error ${response.status} fetching log`);
                    }).catch(() => {
                        throw new Error(`HTTP error ${response.status} fetching log (no JSON error body)`);
                    });
                }
                return response.json();
            })
            .then(data => {
                if (liveLogArea) {
                    // Append new log entries rather than replacing, if that's desired,
                    // but simple replacement is easier for now based on server sending full log.
                    liveLogArea.textContent = data.log.join('\n');
                    liveLogArea.scrollTop = liveLogArea.scrollHeight; // Auto-scroll to bottom
                }
                
                if (startMigrationButton) { // Check if button exists
                    if (data.is_migrating) {
                        startMigrationButton.disabled = true;
                        startMigrationButton.textContent = 'Migration in Progress...';
                        if (migrationStateElement) migrationStateElement.textContent = 'Status: Migrating...';
                    } else {
                        startMigrationButton.disabled = false;
                        startMigrationButton.textContent = 'Start Full Migration (Groups, Projects, Repos)';
                        if (migrationStateElement) migrationStateElement.textContent = 'Status: Idle / Completed';
                        if (pollingInterval) {
                            clearInterval(pollingInterval); 
                            pollingInterval = null; // Clear interval ID
                        }
                    }
                }
            })
            .catch(error => {
                console.error('Error fetching log:', error);
                if (liveLogArea) {
                    // Avoid clearing existing log on fetch error, just append error
                    const currentLog = liveLogArea.textContent;
                    liveLogArea.textContent = currentLog + (currentLog ? '\n' : '') + 'Error fetching log: ' + error.message;
                    liveLogArea.scrollTop = liveLogArea.scrollHeight;
                }
                if (migrationStateElement) migrationStateElement.textContent = 'Status: Error fetching log.';
                
                // Optionally stop polling on repeated errors, or implement backoff
                if (pollingInterval) {
                    // clearInterval(pollingInterval); // Decide if you want to stop on error
                    // pollingInterval = null;
                }
                if (startMigrationButton) { // Check if button exists
                     // Don't re-enable start button just because log fetch failed if migration might still be running
                     // The is_migrating flag from server is the source of truth for this.
                }
            });
    }

    function pollStatus() {
        fetchLog(); // Initial fetch
        if (pollingInterval) clearInterval(pollingInterval); // Clear any existing interval just in case

        // Start polling only if the button is in a state that implies migration is active
        // or could become active. A better check is the 'is_migrating' flag from an initial status check.
        if (startMigrationButton && startMigrationButton.disabled) { 
            pollingInterval = setInterval(fetchLog, pollingTime);
        } else if (startMigrationButton && !startMigrationButton.disabled) {
            // If button is enabled, means migration is not running (or just finished), so don't start polling.
            // However, we might want one initial fetch on page load regardless.
        }
    }
    
    // --- Initial Page Load Logic ---
    // Fetch initial status and log. Start polling if migration is already in progress.
    // This handles page reloads while a migration is running in the background.
    fetch(getStatusLogUrl)
        .then(response => response.json())
        .then(data => {
            if (liveLogArea) { // Update log area on initial load
                liveLogArea.textContent = data.log.join('\n');
                liveLogArea.scrollTop = liveLogArea.scrollHeight;
            }
            if (startMigrationButton) { // Check if button exists
                if (data.is_migrating) {
                    startMigrationButton.disabled = true;
                    startMigrationButton.textContent = 'Migration in Progress...';
                    if (migrationStateElement) migrationStateElement.textContent = 'Status: Migrating...';
                    pollStatus(); // Start polling as migration is active
                } else {
                    startMigrationButton.disabled = false;
                    startMigrationButton.textContent = 'Start Full Migration (Groups, Projects, Repos)';
                    if (migrationStateElement) migrationStateElement.textContent = 'Status: Idle / Completed';
                }
            }
        })
        .catch(error => {
            console.error("Initial status fetch failed:", error);
            if (migrationStateElement) migrationStateElement.textContent = 'Status: Could not fetch initial status.';
        });

}); // End of DOMContentLoaded