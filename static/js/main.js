document.addEventListener('DOMContentLoaded', function() {
    const startMigrationButton = document.getElementById('startMigrationButton');
    const liveLogOutput = document.getElementById('liveLogOutput');
    const clearLogButton = document.getElementById('clearLogButton');
    const overallStatusElement = document.getElementById('overallStatus');
    const currentActionElement = document.getElementById('currentActionText');
    const statsContainer = document.getElementById('statsContainer');
    const errorMessageElement = document.getElementById('errorMessage');
    const logCountElement = document.getElementById('logCount');

    let pollingInterval;
    const pollingTime = 3000; // Poll every 3 seconds

    const startMigrationUrl = "/start-migration"; 
    const getStatusUrl = "/get-status"; // Changed from get-status-log

    function updateButtonState(isMigrating) {
        if (startMigrationButton) {
            startMigrationButton.disabled = isMigrating;
            startMigrationButton.textContent = isMigrating ? 'Migration in Progress...' : 'Start Full Migration (Groups, Projects, Repos)';
        }
    }
    
    function updateOverallStatusUI(statusData) {
        if (overallStatusElement) {
            overallStatusElement.textContent = statusData.status.replace("_", " ").replace(/\b\w/g, l => l.toUpperCase());
        }
        if (currentActionElement) {
            currentActionElement.textContent = statusData.current_action || "Waiting...";
        }
        if (errorMessageElement) {
            if (statusData.error_message) {
                errorMessageElement.textContent = `Error: ${statusData.error_message}`;
                errorMessageElement.style.display = 'block';
            } else {
                errorMessageElement.style.display = 'none';
            }
        }
    }

    function updateStatsUI(stats) {
        if (!statsContainer) return;
        statsContainer.innerHTML = ''; // Clear previous stats

        const sectionOrder = ['groups', 'projects']; // Define order

        sectionOrder.forEach(sectionKey => {
            if (stats[sectionKey]) {
                const stat = stats[sectionKey];
                const percentage = stat.total > 0 ? (stat.completed / stat.total) * 100 : 0;
                
                const statDiv = document.createElement('div');
                statDiv.className = 'stat-item';
                statDiv.innerHTML = `
                    <h6>${sectionKey.charAt(0).toUpperCase() + sectionKey.slice(1)} Migration</h6>
                    <p>Processed: <span class="font-weight-bold">${stat.completed}</span> / ${stat.total}</p>
                    ${stat.current_item_name ? `<p class="text-muted small">Current: ${stat.current_item_name.length > 50 ? stat.current_item_name.substring(0,47)+'...' : stat.current_item_name}</p>` : ''}
                    <div class="progress">
                        <div class="progress-bar ${percentage === 100 ? 'bg-success' : 'bg-info'}" role="progressbar" style="width: ${percentage}%;" aria-valuenow="${percentage}" aria-valuemin="0" aria-valuemax="100">
                           ${Math.round(percentage)}%
                        </div>
                    </div>
                `;
                statsContainer.appendChild(statDiv);
            }
        });
    }
    
    function updateLogUI(logEntries) {
        if (liveLogOutput) {
            liveLogOutput.innerHTML = logEntries.map(log => {
                let colorClass = "text-light"; // Default for info
                if (log.type === "warning") colorClass = "text-warning";
                if (log.type === "error") colorClass = "text-danger font-weight-bold";
                return `<div class="${colorClass}"><span class="text-muted">[${log.timestamp}]</span> ${log.message}</div>`;
            }).join('');
            liveLogOutput.scrollTop = liveLogOutput.scrollHeight;
        }
        if(logCountElement) {
            logCountElement.textContent = logEntries.length;
        }
    }

    function fetchAndUpdateStatus() {
        fetch(getStatusUrl)
            .then(response => {
                if (!response.ok) throw new Error(`HTTP error ${response.status} fetching status`);
                return response.json();
            })
            .then(data => {
                updateButtonState(data.status === "running" || data.status === "initializing" || data.status === "migrating_groups" || data.status === "migrating_projects");
                updateOverallStatusUI(data);
                updateStatsUI(data.stats);
                updateLogUI(data.logs);

                if (!(data.status === "running" || data.status === "initializing" || data.status === "migrating_groups" || data.status === "migrating_projects") && pollingInterval) {
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                }
            })
            .catch(error => {
                console.error('Error fetching status:', error);
                if (overallStatusElement) overallStatusElement.textContent = "Error fetching status.";
                if (pollingInterval) clearInterval(pollingInterval); // Stop polling on error
                pollingInterval = null;
                updateButtonState(false); // Re-enable button on error
            });
    }

    if (migrationForm && startMigrationButton) {
        migrationForm.addEventListener('submit', function(event) {
            event.preventDefault();
            startMigrationButton.disabled = true;
            startMigrationButton.textContent = 'Initiating Migration...';
            if (overallStatusElement) overallStatusElement.textContent = 'Initiating...';
            if (errorMessageElement) errorMessageElement.style.display = 'none';


            fetch(startMigrationUrl, { method: 'POST' })
                .then(response => {
                    if (!response.ok) return response.json().then(err => { throw err; });
                    return response.json();
                })
                .then(data => {
                    alert(data.message); // Simple feedback
                    if (data.status === 'success' || data.status === 'warning') { // warning if already running
                        if (!pollingInterval) { // Start polling only if not already polling
                           fetchAndUpdateStatus(); // Immediate update
                           pollingInterval = setInterval(fetchAndUpdateStatus, pollingTime);
                        }
                    } else { // On failure to start
                        updateButtonState(false);
                         if (overallStatusElement) overallStatusElement.textContent = `Idle (Start Failed: ${data.message || 'Unknown'})`;
                    }
                })
                .catch(error => {
                    console.error('Error starting migration:', error);
                    alert('Error starting migration: ' + (error.message || error));
                    updateButtonState(false);
                    if (overallStatusElement) overallStatusElement.textContent = 'Error starting migration.';
                });
        });
    }

    if (clearLogButton && liveLogOutput) {
        clearLogButton.addEventListener('click', function() {
            liveLogOutput.innerHTML = '<div class="text-muted">[Client-side log display cleared]</div>';
            if(logCountElement) logCountElement.textContent = 0;
            // Server log is not affected
        });
    }

    // Initial status check on page load
    fetchAndUpdateStatus();
    // If the initial status indicates migration is ongoing, start polling
    fetch(getStatusUrl).then(r=>r.json()).then(data => {
        if(data.status === "running" || data.status === "initializing" || data.status === "migrating_groups" || data.status === "migrating_projects"){
            if (!pollingInterval) {
                pollingInterval = setInterval(fetchAndUpdateStatus, pollingTime);
            }
        }
    });

}); // End DOMContentLoaded