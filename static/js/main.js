document.addEventListener('DOMContentLoaded', () => {
    lucide.createIcons(); // Initialize all lucide icons on the page

    // --- DOM Elements ---
    const startMigrationButton = document.getElementById('startMigrationButton');
    const migrationButtonText = document.getElementById('migrationButtonText');
    
    const migrationStatusDisplay = document.getElementById('migrationStatusDisplay');
    const statusIconDisplay = document.getElementById('statusIconDisplay');
    const statusTextDisplay = document.getElementById('statusTextDisplay');
    
    const overallProgressContainer = document.getElementById('overallProgressContainer');
    const overallProgressBar = document.getElementById('overallProgressBar');
    const overallProgressPercent = document.getElementById('overallProgressPercent');
    
    const currentSectionTitleElement = document.getElementById('currentSectionTitle');
    const currentSectionDescriptionElement = document.getElementById('currentSectionDescription');
    
    const statsContainer = document.getElementById('statsContainer');
    const currentActionIndicator = document.getElementById('currentActionIndicator');
    
    const completedStatusDisplay = document.getElementById('completedStatusDisplay');
    const errorStatusDisplay = document.getElementById('errorStatusDisplay');
    const errorMessageText = document.getElementById('errorMessageText');

    const logOutputContainer = document.getElementById('logOutputContainer');
    const logCountElement = document.getElementById('logCount');
    const clearLogButton = document.getElementById('clearLogButton');

    const movingFilesContainer = document.getElementById('movingFilesContainer');

    // --- State & Configuration ---
    let pollingInterval;
    const pollingTime = 3000; // Poll every 3 seconds
    let movingFileIdCounter = 0;
    const MAX_MOVING_FILES = 15;
    let activeMovingFiles = [];

    const startMigrationUrl = "/start-migration"; 
    const getStatusUrl = "/get-status";

    const statConfig = {
        groups: { icon: "users", color: "blue", label: "Groups Migration" },
        projects: { icon: "box", color: "purple", label: "Projects & Repositories" },
        // If backend adds issues/MRs to stats, define them here:
        // issues: { icon: "file-text", color: "yellow", label: "Issues Migration" },
        // mergeRequests: { icon: "git-merge", color: "red", label: "Merge Requests Migration" },
    };
    const fileVisualIcons = ['file-text', 'git-commit', 'git-branch', 'folder-git-2'];


    // --- Event Listeners ---
    if (startMigrationButton) {
        startMigrationButton.addEventListener('click', handleStartMigration);
    }
    if (clearLogButton) {
        clearLogButton.addEventListener('click', () => {
            if (logOutputContainer) logOutputContainer.innerHTML = '<div class="text-gray-500 italic">[Client-side log display cleared]</div>';
            if (logCountElement) logCountElement.textContent = '0';
        });
    }

    // --- Core Functions ---
    function handleStartMigration() {
        if (startMigrationButton.disabled) return; // Already running or request pending

        updateButtonState(true, 'Initiating...');
        updateOverallStatusUI({ status: 'initializing', current_action: 'Sending start request to server...' });
        completedStatusDisplay.classList.add('hidden');
        errorStatusDisplay.classList.add('hidden');

        fetch(startMigrationUrl, { method: 'POST' })
            .then(response => {
                if (!response.ok) return response.json().then(err => { throw err || { message: `HTTP error ${response.status}` }; });
                return response.json();
            })
            .then(data => {
                // Server responds success if task is queued or already running
                if (data.status === 'success' || data.status === 'warning') { // warning if already running
                    // UI will update based on polled status, no need to set text here
                    if (!pollingInterval) {
                        fetchAndUpdateStatus(); // Immediate update
                        pollingInterval = setInterval(fetchAndUpdateStatus, pollingTime);
                    }
                } else {
                    updateButtonState(false, 'Start Failed - Retry?');
                    updateOverallStatusUI({ status: 'error', current_action: data.message || 'Failed to start migration on server' });
                    if(errorMessageText) errorMessageText.textContent = data.message || 'Failed to start migration on server';
                    errorStatusDisplay.classList.remove('hidden');
                }
            })
            .catch(error => {
                console.error('Error starting migration:', error);
                updateButtonState(false, 'Start Failed - Retry?');
                updateOverallStatusUI({ status: 'error', current_action: 'Error communicating with server to start migration.' });
                 if(errorMessageText) errorMessageText.textContent = error.message || 'Communication error.';
                 errorStatusDisplay.classList.remove('hidden');
            });
    }

    function updateButtonState(isMigrating, buttonTextContent = 'Start Full Migration') {
        if (!startMigrationButton || !migrationButtonText) return;
        startMigrationButton.disabled = isMigrating;
        migrationButtonText.textContent = buttonTextContent;
        
        const iconEl = startMigrationButton.querySelector('i[data-lucide]');
        if (iconEl) iconEl.setAttribute('data-lucide', isMigrating ? 'pause-circle' : 'play-circle');
        
        startMigrationButton.classList.toggle('bg-green-500', !isMigrating);
        startMigrationButton.classList.toggle('hover:bg-green-600', !isMigrating);
        startMigrationButton.classList.toggle('text-white', !isMigrating);
        startMigrationButton.classList.toggle('bg-gray-400', isMigrating);
        startMigrationButton.classList.toggle('text-gray-700', isMigrating);
        startMigrationButton.classList.toggle('cursor-not-allowed', isMigrating);
        lucide.createIcons();
    }

    function updateOverallStatusUI(statusData) {
        // Update main status display
        let iconName = 'info';
        let statusColorClasses = 'bg-gray-100 text-gray-700';
        let statusText = statusData.status.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());

        if (statusData.status === "completed") {
            iconName = "check-circle"; statusColorClasses = "bg-green-100 text-green-700";
            completedStatusDisplay.classList.remove('hidden'); errorStatusDisplay.classList.add('hidden');
        } else if (statusData.status === "error") {
            iconName = "alert-triangle"; statusColorClasses = "bg-red-100 text-red-700";
            completedStatusDisplay.classList.add('hidden'); errorStatusDisplay.classList.remove('hidden');
            if(errorMessageText && statusData.error_message) errorMessageText.textContent = statusData.error_message;
            else if(errorMessageText) errorMessageText.textContent = "An unspecified error occurred.";
        } else if (["running", "initializing", "migrating_groups", "migrating_projects"].includes(statusData.status)) {
            iconName = "loader"; statusColorClasses = "bg-blue-100 text-blue-700";
            if (statusIconDisplay) statusIconDisplay.innerHTML = '<span class="inline-block w-5 h-5 mr-2 rounded-full bg-blue-500 animate-pulse-icon"></span>'; // Custom pulse
             completedStatusDisplay.classList.add('hidden'); errorStatusDisplay.classList.add('hidden');
        } else { // idle
             statusColorClasses = "bg-gray-100 text-gray-700";
             iconName = "info";
             completedStatusDisplay.classList.add('hidden'); errorStatusDisplay.classList.add('hidden');
        }
        if (migrationStatusDisplay) migrationStatusDisplay.className = `p-4 rounded-lg text-center transition-all duration-300 ${statusColorClasses}`;
        if (statusTextDisplay) statusTextDisplay.textContent = statusText;
        if (statusIconDisplay && iconName !== "loader") {
            statusIconDisplay.innerHTML = `<i data-lucide="${iconName}" class="inline-block mr-2 w-6 h-6"></i>`;
        }

        // Update current section titles
        if (currentSectionTitleElement) currentSectionTitleElement.textContent = statusData.current_action || "Migration Dashboard";
        if (currentSectionDescriptionElement) {
            if (statusData.status === "error" && statusData.error_message) {
                currentSectionDescriptionElement.textContent = `Last Error: ${statusData.error_message.substring(0,100)}...`;
            } else if (statusData.status === "completed") {
                currentSectionDescriptionElement.textContent = "All tasks finished.";
            } else if (statusData.status === "idle"){
                currentSectionDescriptionElement.textContent = "Ready to start migration.";
            } else {
                 currentSectionDescriptionElement.textContent = "Monitor the GitLab data migration process.";
            }
        }
        
        // Overall Progress Bar
        let overallProgress = 0;
        let showOverallProgress = false;
        if (statusData.stats && (statusData.status === "running" || statusData.status === "migrating_groups" || statusData.status === "migrating_projects")) {
            showOverallProgress = true;
            const { groups, projects } = statusData.stats;
            const totalGroups = groups.total || 0;
            const completedGroups = groups.completed || 0;
            const totalProjects = projects.total || 0;
            const completedProjects = projects.completed || 0;

            if (statusData.status === "migrating_groups") {
                overallProgress = totalGroups > 0 ? Math.round((completedGroups / totalGroups) * 50) : 0; // Groups are 50% of total
            } else if (statusData.status === "migrating_projects") {
                overallProgress = 50 + (totalProjects > 0 ? Math.round((completedProjects / totalProjects) * 50) : 0); // Projects are other 50%
            }
        } else if (statusData.status === "completed") {
            showOverallProgress = true;
            overallProgress = 100;
        }

        if (overallProgressContainer) {
            if (showOverallProgress) {
                overallProgressContainer.classList.remove('hidden');
                overallProgressBar.style.width = `${overallProgress}%`;
                overallProgressBar.textContent = `${overallProgress}%`;
                overallProgressPercent.textContent = `${overallProgress}%`;
                overallProgressBar.classList.toggle('bg-green-500', statusData.status === "completed");
                overallProgressBar.classList.toggle('bg-purple-500', statusData.status !== "completed");
            } else {
                overallProgressContainer.classList.add('hidden');
            }
        }
        
        // Current Action Indicator at bottom of visualization
        if (currentActionIndicator) {
            if (statusData.status === "migrating_groups" && statusData.stats?.groups?.current_item_name) {
                currentActionIndicator.classList.remove('hidden');
                currentActionIndicator.innerHTML = `<i data-lucide="users" class="mr-2 w-4 h-4 text-blue-500"></i> Group: ${statusData.stats.groups.current_item_name}`;
            } else if (statusData.status === "migrating_projects" && statusData.stats?.projects?.current_item_name) {
                currentActionIndicator.classList.remove('hidden');
                currentActionIndicator.innerHTML = `<i data-lucide="box" class="mr-2 w-4 h-4 text-purple-500"></i> Project: ${statusData.stats.projects.current_item_name}`;
            } else if (statusData.status === "running" || statusData.status === "initializing") {
                currentActionIndicator.classList.remove('hidden');
                currentActionIndicator.innerHTML = `<i data-lucide="loader-2" class="mr-2 w-4 h-4 animate-spin"></i> ${statusData.current_action}`;
            }
            else {
                currentActionIndicator.classList.add('hidden');
            }
        }
        lucide.createIcons(); // Re-render icons
    }

    function updateStatsUI(stats) {
        if (!statsContainer || !stats) return;
        statsContainer.innerHTML = ''; 

        Object.keys(statConfig).forEach(sectionKey => {
            if (stats[sectionKey]) {
                const statData = stats[sectionKey];
                const config = statConfig[sectionKey];
                const percentage = statData.total > 0 ? Math.round((statData.completed / statData.total) * 100) : 0;
                
                const statDiv = document.createElement('div');
                statDiv.className = 'p-3 bg-gray-50 rounded-lg shadow-sm border border-gray-200';
                statDiv.innerHTML = `
                    <div class="flex items-center mb-1.5">
                      <i data-lucide="${config.icon}" class="mr-2 text-${config.color}-500 w-5 h-5"></i>
                      <h3 class="font-semibold text-gray-700 text-md">${config.label}</h3>
                    </div>
                    <div class="ml-7">
                      <div class="flex justify-between text-xs text-gray-500 mb-0.5">
                        <span>Processed:</span>
                        <span class="font-medium text-gray-700">${statData.completed} / ${statData.total || '...'}</span>
                      </div>
                      <div class="w-full h-2.5 bg-gray-200 rounded-full overflow-hidden">
                        <div 
                          class="h-2.5 bg-${config.color}-500 rounded-full transition-width duration-300" 
                          style="width: ${percentage}%">
                        </div>
                      </div>
                      ${statData.current_item_name ? `<p class="text-xs text-gray-400 mt-1 truncate" title="${statData.current_item_name}">Current: ${statData.current_item_name}</p>` : '<p class="text-xs text-gray-400 mt-1">-</p>'}
                    </div>
                `;
                statsContainer.appendChild(statDiv);
            }
        });
        lucide.createIcons();
    }
    
    function updateLogUI(logEntries) {
        if (!logOutputContainer) return;
        logOutputContainer.innerHTML = logEntries.map(log => {
            let colorClass = "text-gray-300"; // Default for info
            let icon = "info";
            if (log.type === "warning") { colorClass = "text-yellow-400"; icon="alert-circle"; }
            if (log.type === "error") { colorClass = "text-red-400 font-semibold"; icon="alert-triangle"; }
            return `<div class="${colorClass} mb-0.5 flex items-start"><i data-lucide="${icon}" class="w-3 h-3 mr-1.5 mt-0.5 flex-shrink-0"></i><span class="text-gray-500">[${log.timestamp}] </span><span>${log.message}</span></div>`;
        }).join('');
        // Do not auto-scroll if user has scrolled up
        if (logOutputContainer.scrollTop + logOutputContainer.clientHeight >= logOutputContainer.scrollHeight - 20) {
             logOutputContainer.scrollTop = logOutputContainer.scrollHeight;
        }
        if(logCountElement) logCountElement.textContent = logEntries.length;
        lucide.createIcons({context: logOutputContainer});
    }
    
    // --- Moving Files Animation ---
    function createAndAnimateFile() {
        if (!movingFilesContainer || activeMovingFiles.length >= MAX_MOVING_FILES || Math.random() > 0.25) return; // Reduce frequency

        const fileEl = document.createElement('div');
        fileEl.className = 'moving-file';
        const iconType = fileVisualIcons[Math.floor(Math.random() * fileVisualIcons.length)];
        fileEl.innerHTML = `<i data-lucide="${iconType}" class="text-indigo-400 w-4 h-4"></i>`;
        
        const startY = Math.random() * 70 + 15; // % from top, avoiding edges
        fileEl.style.top = `${startY}%`;
        fileEl.style.left = '25%'; // Start near source server visual (adjusted for new layout)
        movingFilesContainer.appendChild(fileEl);
        lucide.createIcons({ elements: [fileEl.querySelector('i')] });

        activeMovingFiles.push(fileEl);

        let currentLeft = 25;
        const animationInterval = setInterval(() => {
            currentLeft += 1; // Speed of movement
            fileEl.style.left = `${currentLeft}%`;
            if (currentLeft >= 75) { // End near target server visual (adjusted)
                clearInterval(animationInterval);
                if (fileEl.parentElement) fileEl.parentElement.removeChild(fileEl);
                activeMovingFiles = activeMovingFiles.filter(f => f !== fileEl);
            }
        }, 60); 
    }

    function fetchAndUpdateStatus() {
        fetch(getStatusUrl)
            .then(response => {
                if (!response.ok) throw new Error(`HTTP error ${response.status}`);
                return response.json();
            })
            .then(data => {
                const isCurrentlyMigrating = data.status === "running" || 
                                            data.status === "initializing" || 
                                            data.status === "migrating_groups" || 
                                            data.status === "migrating_projects";
                
                updateButtonState(isCurrentlyMigrating, isCurrentlyMigrating ? 'Migration in Progress...' : 'Start Full Migration');
                updateOverallStatusUI(data); // This now handles the main status text/icon and progress bar
                updateStatsUI(data.stats);
                updateLogUI(data.logs);

                if (isCurrentlyMigrating) {
                    createAndAnimateFile(); // Trigger file animation
                } else {
                    if (pollingInterval) clearInterval(pollingInterval);
                    pollingInterval = null;
                    movingFilesContainer.innerHTML = ''; // Clear animation elements
                    activeMovingFiles = [];
                }
            })
            .catch(error => {
                console.error('Error fetching status:', error);
                updateOverallStatusUI({status: "error", current_action: "Error fetching status from server.", error_message: error.message});
                if (pollingInterval) clearInterval(pollingInterval);
                pollingInterval = null;
                updateButtonState(false, 'Start Failed - Retry?');
            });
    }
    
    // --- Initial Page Load Logic ---
    fetchAndUpdateStatus(); // Fetch status immediately on load
    // Determine if polling should start based on initial status
    fetch(getStatusUrl)
        .then(r => r.json())
        .then(data => {
            const isInitiallyMigrating = data.status === "running" || 
                                       data.status === "initializing" ||
                                       data.status === "migrating_groups" ||
                                       data.status === "migrating_projects";
            if (isInitiallyMigrating) {
                if (!pollingInterval) {
                    pollingInterval = setInterval(fetchAndUpdateStatus, pollingTime);
                }
            }
        }).catch(e => {
            console.error("Error on initial status check for polling:", e);
            updateOverallStatusUI({status: "error", current_action: "Could not connect to migration backend."});
        });

}); // End DOMContentLoaded