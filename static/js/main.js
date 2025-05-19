document.addEventListener('DOMContentLoaded', () => {
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
    const pollingTime = 3000; 
    let movingFileIdCounter = 0;
    const MAX_MOVING_FILES = 15;
    let activeMovingFiles = [];

    const startMigrationUrl = "/start-migration"; 
    const getStatusUrl = "/get-status";

    const statConfig = {
        groups: { icon: "users", color: "blue", label: "Groups Migration" },
        projects: { icon: "package", color: "purple", label: "Projects & Repositories" }, // Changed icon
    };
    const fileVisualIcons = ['file-text', 'git-commit', 'git-branch', 'folder-git-2', 'package-search'];


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
        if (startMigrationButton.disabled) return;

        updateButtonState(true, 'Initiating...');
        updateMainStatusDisplay({ status: 'initializing', current_action: 'Sending start request to server...' });
        completedStatusDisplay.classList.add('hidden');
        errorStatusDisplay.classList.add('hidden');
        if(errorMessageText) errorMessageText.textContent = "";


        fetch(startMigrationUrl, { method: 'POST' })
            .then(response => {
                if (!response.ok) return response.json().then(err => { throw err || { message: `HTTP error ${response.status}` }; });
                return response.json();
            })
            .then(data => {
                if (data.status === 'success' || data.status === 'warning') { 
                    if (!pollingInterval) {
                        fetchAndUpdateStatus(); 
                        pollingInterval = setInterval(fetchAndUpdateStatus, pollingTime);
                    }
                } else {
                    updateButtonState(false, 'Start Failed - Retry?');
                    updateMainStatusDisplay({ status: 'error', current_action: data.message || 'Failed to start migration on server' });
                    if(errorMessageText) errorMessageText.textContent = data.message || 'Failed to start migration on server';
                    errorStatusDisplay.classList.remove('hidden');
                }
            })
            .catch(error => {
                console.error('Error starting migration:', error);
                updateButtonState(false, 'Start Failed - Retry?');
                updateMainStatusDisplay({ status: 'error', current_action: 'Error communicating with server.' });
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
        if (lucide) lucide.createIcons({elements: [startMigrationButton]});
    }
    
    function updateMainStatusDisplay(statusData) {
        let iconName = 'info';
        let statusColorClasses = 'bg-gray-100 text-gray-700';
        let statusText = statusData.status.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());

        completedStatusDisplay.classList.add('hidden'); 
        errorStatusDisplay.classList.add('hidden');

        if (statusData.status === "completed") {
            iconName = "check-circle"; statusColorClasses = "bg-green-100 text-green-700";
            completedStatusDisplay.classList.remove('hidden');
        } else if (statusData.status === "error") {
            iconName = "alert-triangle"; statusColorClasses = "bg-red-100 text-red-700";
            errorStatusDisplay.classList.remove('hidden');
            if(errorMessageText && statusData.error_message) errorMessageText.textContent = statusData.error_message;
            else if(errorMessageText) errorMessageText.textContent = "An unspecified error occurred during migration.";
        } else if (["running", "initializing", "migrating_groups", "migrating_projects"].includes(statusData.status)) {
            iconName = "loader"; statusColorClasses = "bg-blue-100 text-blue-700";
            if (statusIconDisplay) statusIconDisplay.innerHTML = '<span class="inline-block w-6 h-6 mr-2 rounded-full bg-blue-500 animate-pulse-icon"></span>';
        } else { // idle
             statusColorClasses = "bg-gray-100 text-gray-800"; // Changed text color
             iconName = "info";
             if (statusIconDisplay) statusIconDisplay.innerHTML = `<i data-lucide="${iconName}" class="inline-block mr-2 w-6 h-6"></i>`;
        }
        if (migrationStatusDisplay) migrationStatusDisplay.className = `p-4 rounded-lg text-center transition-all duration-300 ${statusColorClasses}`;
        if (statusTextDisplay) statusTextDisplay.textContent = statusText;
        if (statusIconDisplay && iconName !== "loader") { // Render if not loader (loader is custom span)
            statusIconDisplay.innerHTML = `<i data-lucide="${iconName}" class="inline-block mr-2 w-6 h-6"></i>`;
        }

        if (currentSectionTitleElement) currentSectionTitleElement.textContent = statusData.current_action || "Migration Dashboard";
        if (currentSectionDescriptionElement) {
            if (statusData.status === "error" && statusData.error_message) currentSectionDescriptionElement.textContent = `Last Error: ${statusData.error_message.substring(0,100)}...`;
            else if (statusData.status === "completed") currentSectionDescriptionElement.textContent = "All tasks finished successfully.";
            else if (statusData.status === "idle") currentSectionDescriptionElement.textContent = "Ready to start migration.";
            else currentSectionDescriptionElement.textContent = "Monitor the GitLab data migration process.";
        }
        
        let overallProgress = 0;
        let showOverallProgress = false;
        if (statusData.stats && (statusData.status === "migrating_groups" || statusData.status === "migrating_projects")) {
            showOverallProgress = true;
            const { groups, projects } = statusData.stats;
            const totalGroups = Math.max(1, groups.total || 1); // Avoid division by zero, assume at least 1 if unknown
            const completedGroups = groups.completed || 0;
            const totalProjects = Math.max(1, projects.total || 1);
            const completedProjects = projects.completed || 0;

            if (statusData.status === "migrating_groups") {
                overallProgress = Math.round((completedGroups / totalGroups) * 50);
            } else if (statusData.status === "migrating_projects") {
                overallProgress = 50 + Math.round((completedProjects / totalProjects) * 50);
            }
            overallProgress = Math.min(100, Math.max(0, overallProgress)); // Clamp between 0-100
        } else if (statusData.status === "completed") {
            showOverallProgress = true; overallProgress = 100;
        } else if (statusData.status === "initializing" || statusData.status === "running"){
             showOverallProgress = true; overallProgress = 1; // Show a sliver for initializing/running
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
        
        if (currentActionIndicator) {
            let indicatorText = ""; let indicatorIcon = "loader-2"; let indicatorColor = "text-gray-700";
            if (statusData.status === "migrating_groups" && statusData.stats?.groups) {
                indicatorText = `Group: ${statusData.stats.groups.current_item_name || 'Scanning...'}`; indicatorIcon = "users"; indicatorColor = "text-blue-600";
            } else if (statusData.status === "migrating_projects" && statusData.stats?.projects) {
                indicatorText = `Project: ${statusData.stats.projects.current_item_name || 'Scanning...'}`; indicatorIcon = "package"; indicatorColor = "text-purple-600";
            } else if (statusData.status === "running" || statusData.status === "initializing") {
                indicatorText = statusData.current_action; indicatorIcon = "loader-2"; indicatorColor = "text-indigo-600";
            } else if (statusData.status === "idle") {
                 indicatorText = "Idle. Ready to start."; indicatorIcon = "info";
            } else if (statusData.status === "completed") {
                 indicatorText = "Migration Completed!"; indicatorIcon = "check-circle"; indicatorColor = "text-green-600";
            } else if (statusData.status === "error") {
                 indicatorText = "Error Occurred!"; indicatorIcon = "alert-triangle"; indicatorColor = "text-red-600";
            }

            if (indicatorText) {
                currentActionIndicator.classList.remove('hidden');
                currentActionIndicator.innerHTML = `<i data-lucide="${indicatorIcon}" class="mr-2 w-4 h-4 ${indicatorIcon === 'loader-2' ? 'animate-spin' : ''} ${indicatorColor}"></i> ${indicatorText}`;
            } else {
                currentActionIndicator.classList.add('hidden');
            }
        }
        if (lucide) lucide.createIcons();
    }

    function updateStatsUI(stats) {
        if (!statsContainer || !stats) {
            statsContainer.innerHTML = '<div class="text-gray-500 text-sm p-3">Stats not available yet...</div>';
            return;
        }
        statsContainer.innerHTML = ''; 

        Object.keys(statConfig).forEach(sectionKey => {
            if (stats[sectionKey]) {
                const statData = stats[sectionKey];
                const config = statConfig[sectionKey];
                const total = statData.total || 0;
                const completed = statData.completed || 0;
                const percentage = total > 0 ? Math.round((completed / total) * 100) : (completed > 0 ? 100 : 0);
                
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
                        <span class="font-medium text-gray-700">${completed} / ${total || '...'}</span>
                      </div>
                      <div class="w-full h-2.5 bg-gray-300 rounded-full overflow-hidden">
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
        if (lucide) lucide.createIcons({context: statsContainer});
    }
    
    function updateLogUI(logEntries) {
        if (!logOutputContainer) return;
        logOutputContainer.innerHTML = logEntries.map(log => {
            let colorClass = "text-gray-300"; 
            let icon = "info";
            if (log.type === "warning") { colorClass = "text-yellow-400"; icon="alert-circle"; }
            if (log.type === "error") { colorClass = "text-red-400 font-semibold"; icon="alert-triangle"; }
            return `<div class="${colorClass} mb-0.5 flex items-start"><i data-lucide="${icon}" class="w-3 h-3 mr-1.5 mt-0.5 flex-shrink-0"></i><span class="text-gray-500">[${log.timestamp}] </span><span>${log.message}</span></div>`;
        }).join('');
        
        if (logOutputContainer.scrollTop + logOutputContainer.clientHeight >= logOutputContainer.scrollHeight - 30) {
             logOutputContainer.scrollTop = logOutputContainer.scrollHeight;
        }
        if(logCountElement) logCountElement.textContent = logEntries.length;
        if (lucide) lucide.createIcons({context: logOutputContainer});
    }
    
    // --- Moving Files Animation ---
    function createAndAnimateFile() {
        if (!movingFilesContainer || activeMovingFiles.length >= MAX_MOVING_FILES || Math.random() > 0.3) return;

        const fileEl = document.createElement('div');
        fileEl.className = 'moving-file p-1 rounded shadow-md'; // Added padding and shadow
        const iconType = fileVisualIcons[Math.floor(Math.random() * fileVisualIcons.length)];
        const colors = ["text-blue-400", "text-green-400", "text-purple-400", "text-yellow-400", "text-pink-400"];
        const iconColor = colors[Math.floor(Math.random() * colors.length)];

        fileEl.innerHTML = `<i data-lucide="${iconType}" class="${iconColor} w-3 h-3"></i>`;
        
        const startY = Math.random() * 60 + 20; 
        fileEl.style.top = `${startY}%`;
        fileEl.style.left = '28%'; 
        movingFilesContainer.appendChild(fileEl);
        if (lucide) lucide.createIcons({ elements: [fileEl.querySelector('i')] });

        activeMovingFiles.push(fileEl);

        let currentLeft = 28;
        const animationInterval = setInterval(() => {
            currentLeft += (Math.random() * 0.5 + 0.5); // Vary speed slightly
            fileEl.style.left = `${currentLeft}%`;
            if (currentLeft >= 72) { 
                clearInterval(animationInterval);
                if (fileEl.parentElement) fileEl.parentElement.removeChild(fileEl);
                activeMovingFiles = activeMovingFiles.filter(f => f !== fileEl);
            }
        }, 50 + Math.random() * 30); 
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
                updateMainStatusDisplay(data);
                updateStatsUI(data.stats);
                updateLogUI(data.logs);

                if (isCurrentlyMigrating) {
                    createAndAnimateFile(); 
                } else {
                    if (pollingInterval) clearInterval(pollingInterval);
                    pollingInterval = null;
                    if (movingFilesContainer) movingFilesContainer.innerHTML = ''; 
                    activeMovingFiles = [];
                }
            })
            .catch(error => {
                console.error('Error fetching status:', error);
                updateMainStatusDisplay({status: "error", current_action: "Error fetching status from server.", error_message: error.message});
                if (pollingInterval) clearInterval(pollingInterval);
                pollingInterval = null;
                updateButtonState(false, 'Start Failed - Retry?');
            });
    }
    
    function checkLucideAndInit() {
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            console.log("Lucide is ready. Initializing UI.");
            lucide.createIcons(); // Initial full render of static icons
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
                    updateMainStatusDisplay({status: "error", current_action: "Could not connect to backend."});
                });
        } else {
            console.log("Lucide not ready, trying again in 100ms");
            setTimeout(checkLucideAndInit, 100);
        }
    }
    checkLucideAndInit(); // Start the check

}); // End DOMContentLoaded