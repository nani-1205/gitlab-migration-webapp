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
    const completedReportButtons = document.getElementById('completedReportButtons');
    const errorReportButtons = document.getElementById('errorReportButtons');

    const logOutputContainer = document.getElementById('logOutputContainer');
    const logCountElement = document.getElementById('logCount');
    const clearLogButton = document.getElementById('clearLogButton');

    const movingFilesContainer = document.getElementById('movingFilesContainer');

    // --- State & Configuration ---
    let pollingInterval = null;
    const pollingTime = 3000; 
    let animationIntervalId = null;
    let currentMigrationStatus = "idle";
    let lastActiveItemName = "";

    const startMigrationUrl = "/start-migration"; 
    const getStatusUrl = "/get-status";

    const statConfig = {
        users: { icon: "user", colorClass: "text-emerald-400", bgClass: "bg-emerald-500", label: "Users Migration" },
        groups: { icon: "folder-git-2", colorClass: "text-indigo-400", bgClass: "bg-indigo-500", label: "Groups Migration" },
        projects: { icon: "git-branch", colorClass: "text-purple-400", bgClass: "bg-purple-500", label: "Projects & Repositories" },
    };

    // --- Event Listeners ---
    if (startMigrationButton) {
        startMigrationButton.addEventListener('click', handleStartMigration);
    }
    if (clearLogButton) {
        clearLogButton.addEventListener('click', () => {
            if (logOutputContainer) logOutputContainer.innerHTML = '<div class="text-gray-600 italic">[Terminal buffer cleared]</div>';
            if (logCountElement) logCountElement.textContent = '0';
        });
    }

    // --- Animation Handling ---
    function startAnimationLoop() {
        if (animationIntervalId) return;
        console.log("Starting transfer animation loop.");
        animationIntervalId = setInterval(createAndAnimateFile, 250); // Spawn particle every 250ms
    }

    function stopAnimationLoop() {
        if (animationIntervalId) {
            console.log("Stopping transfer animation loop.");
            clearInterval(animationIntervalId);
            animationIntervalId = null;
        }
        if (movingFilesContainer) {
            movingFilesContainer.innerHTML = ''; 
        }
    }

    function createAndAnimateFile() {
        if (!movingFilesContainer) return;

        // Limit the total active elements to prevent performance degradation
        if (movingFilesContainer.children.length >= 25) return;

        const fileEl = document.createElement('div');
        fileEl.className = 'moving-file';

        // Select icons & glows based on active phase
        let iconType = 'file-text';
        let iconColorClass = 'text-indigo-400';
        let glowColor = 'rgba(99, 102, 241, 0.4)';

        if (currentMigrationStatus === 'migrating_users') {
            const userIcons = ['user', 'users'];
            iconType = userIcons[Math.floor(Math.random() * userIcons.length)];
            iconColorClass = 'text-emerald-400';
            glowColor = 'rgba(16, 185, 129, 0.4)';
        } else if (currentMigrationStatus === 'migrating_groups') {
            const groupIcons = ['folder', 'folder-git-2', 'git-branch'];
            iconType = groupIcons[Math.floor(Math.random() * groupIcons.length)];
            iconColorClass = 'text-indigo-400';
            glowColor = 'rgba(99, 102, 241, 0.4)';
        } else if (currentMigrationStatus === 'migrating_projects') {
            const projIcons = ['package', 'git-commit', 'git-pull-request', 'terminal'];
            iconType = projIcons[Math.floor(Math.random() * projIcons.length)];
            iconColorClass = 'text-purple-400';
            glowColor = 'rgba(168, 85, 247, 0.4)';
        } else {
            // Default random git icons
            const defaultIcons = ['file-text', 'git-commit', 'git-branch', 'package'];
            iconType = defaultIcons[Math.floor(Math.random() * defaultIcons.length)];
            iconColorClass = 'text-gray-400';
            glowColor = 'rgba(148, 163, 184, 0.3)';
        }

        let labelHtml = "";
        if (lastActiveItemName) {
            let displayName = lastActiveItemName;
            if (displayName.length > 20) {
                displayName = "..." + displayName.slice(-17);
            }
            labelHtml = `<span class="moving-file-label font-sans text-[9px] text-gray-200 ml-1.5 bg-slate-950 bg-opacity-70 px-1.5 py-0.5 rounded border border-gray-800 shadow-inner">${displayName}</span>`;
            fileEl.classList.add('has-label');
            fileEl.innerHTML = `<i data-lucide="${iconType}" class="${iconColorClass}"></i>${labelHtml}`;
        } else {
            fileEl.innerHTML = `<i data-lucide="${iconType}" class="${iconColorClass}"></i>`;
        }
        fileEl.style.boxShadow = `0 4px 12px rgba(0, 0, 0, 0.5), 0 0 8px ${glowColor}`;

        const startY = Math.random() * 50 + 25; // Random height between 25% and 75%
        fileEl.style.top = `${startY}%`;
        
        movingFilesContainer.appendChild(fileEl);
        
        if (window.lucide) {
            window.lucide.createIcons({ elements: [fileEl.querySelector('i')] });
        }

        // Clean up element once animation ends
        fileEl.addEventListener('animationend', () => {
            fileEl.remove();
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

        currentMigrationStatus = 'initializing';
        startAnimationLoop(); // Instantly start animation for interactive responsiveness

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
                    stopAnimationLoop();
                    updateButtonState(false, 'Start Failed - Retry?');
                    updateMainStatusDisplay({ status: 'error', current_action: data.message || 'Failed to start migration on server' });
                    if(errorMessageText) errorMessageText.textContent = data.message || 'Failed to start migration on server';
                    errorStatusDisplay.classList.remove('hidden');
                }
            })
            .catch(error => {
                console.error('Error starting migration:', error);
                stopAnimationLoop();
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
        
        startMigrationButton.classList.toggle('from-emerald-500', !isMigrating);
        startMigrationButton.classList.toggle('to-green-600', !isMigrating);
        startMigrationButton.classList.toggle('hover:from-emerald-400', !isMigrating);
        startMigrationButton.classList.toggle('hover:to-green-500', !isMigrating);
        startMigrationButton.classList.toggle('cursor-pointer', !isMigrating);
        
        startMigrationButton.classList.toggle('from-gray-800', isMigrating);
        startMigrationButton.classList.toggle('to-gray-900', isMigrating);
        startMigrationButton.classList.toggle('border', isMigrating);
        startMigrationButton.classList.toggle('border-gray-700', isMigrating);
        startMigrationButton.classList.toggle('text-gray-500', isMigrating);
        startMigrationButton.classList.toggle('cursor-not-allowed', isMigrating);
        startMigrationButton.classList.toggle('shadow-none', isMigrating);
        
        if (window.lucide) window.lucide.createIcons({elements: [startMigrationButton]});
    }
    
    function updateMainStatusDisplay(statusData) {
        let iconName = 'info';
        let statusColorClasses = 'border border-gray-800 text-gray-400 bg-gray-900 bg-opacity-50';
        let statusText = statusData.status.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());

        completedStatusDisplay.classList.add('hidden'); 
        errorStatusDisplay.classList.add('hidden');

        if (statusData.status === "completed") {
            iconName = "check-circle"; 
            statusColorClasses = "glow-pulse-green border border-emerald-500 bg-emerald-950 bg-opacity-20 text-emerald-400";
            completedStatusDisplay.classList.remove('hidden');
            if (completedReportButtons) {
                if (statusData.stats && statusData.stats.projects && statusData.stats.projects.failed > 0) {
                    completedReportButtons.classList.remove('hidden');
                } else {
                    completedReportButtons.classList.add('hidden');
                }
            }
        } else if (statusData.status === "error") {
            iconName = "alert-triangle"; 
            statusColorClasses = "glow-pulse-red border border-red-500 bg-red-950 bg-opacity-20 text-red-400";
            errorStatusDisplay.classList.remove('hidden');
            if (errorReportButtons) {
                if (statusData.stats && statusData.stats.projects && statusData.stats.projects.failed > 0) {
                    errorReportButtons.classList.remove('hidden');
                } else {
                    errorReportButtons.classList.add('hidden');
                }
            }
            if(errorMessageText && statusData.error_message) errorMessageText.textContent = statusData.error_message;
            else if(errorMessageText) errorMessageText.textContent = "An unspecified error occurred during migration.";
        } else if (["running", "initializing", "migrating_users", "migrating_groups", "migrating_projects"].includes(statusData.status)) {
            iconName = "loader-2"; 
            statusColorClasses = "glow-pulse-blue border border-indigo-500 bg-indigo-950 bg-opacity-20 text-indigo-400";
            if (statusIconDisplay) statusIconDisplay.innerHTML = '<i data-lucide="loader-2" class="inline-block mr-2 w-6 h-6 animate-spin-custom"></i>';
        } else { // idle
             statusColorClasses = "border border-gray-800 text-gray-450 bg-gray-900 bg-opacity-50";
             iconName = "info";
             if (statusIconDisplay) statusIconDisplay.innerHTML = `<i data-lucide="${iconName}" class="inline-block mr-2 w-6 h-6 text-gray-500"></i>`;
        }
        
        if (migrationStatusDisplay) migrationStatusDisplay.className = `status-indicator p-4 rounded-xl text-center transition-all duration-300 ${statusColorClasses}`;
        if (statusTextDisplay) statusTextDisplay.textContent = statusText;
        if (statusIconDisplay && iconName !== "loader-2") { // Render if not loader-2 (loader is custom spin)
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
        if (statusData.stats && (statusData.status === "migrating_users" || statusData.status === "migrating_groups" || statusData.status === "migrating_projects")) {
            showOverallProgress = true;
            const { users, groups, projects } = statusData.stats;
            const totalUsers = Math.max(1, users?.total || 1);
            const completedUsers = users?.completed || 0;
            const totalGroups = Math.max(1, groups?.total || 1);
            const completedGroups = groups?.completed || 0;
            const totalProjects = Math.max(1, projects?.total || 1);
            const completedProjects = projects?.completed || 0;

            if (statusData.status === "migrating_users") {
                overallProgress = Math.round((completedUsers / totalUsers) * 10);
            } else if (statusData.status === "migrating_groups") {
                overallProgress = 10 + Math.round((completedGroups / totalGroups) * 20);
            } else if (statusData.status === "migrating_projects") {
                overallProgress = 30 + Math.round((completedProjects / totalProjects) * 70);
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
            } else {
                overallProgressContainer.classList.add('hidden');
            }
        }
        
        if (currentActionIndicator) {
            let indicatorText = ""; let indicatorIcon = "loader-2"; let indicatorColor = "text-gray-400";
            if (statusData.status === "migrating_users" && statusData.stats?.users) {
                indicatorText = `User: ${statusData.stats.users.current_item_name || 'Scanning...'}`; indicatorIcon = "user"; indicatorColor = "text-emerald-400";
                lastActiveItemName = statusData.stats.users.current_item_name || "";
            } else if (statusData.status === "migrating_groups" && statusData.stats?.groups) {
                indicatorText = `Group: ${statusData.stats.groups.current_item_name || 'Scanning...'}`; indicatorIcon = "folder-git-2"; indicatorColor = "text-indigo-400";
                lastActiveItemName = statusData.stats.groups.current_item_name || "";
            } else if (statusData.status === "migrating_projects" && statusData.stats?.projects) {
                indicatorText = `Project: ${statusData.stats.projects.current_item_name || 'Scanning...'}`; indicatorIcon = "git-branch"; indicatorColor = "text-purple-400";
                lastActiveItemName = statusData.stats.projects.current_item_name || "";
            } else if (statusData.status === "running" || statusData.status === "initializing") {
                indicatorText = statusData.current_action; indicatorIcon = "loader-2"; indicatorColor = "text-indigo-400";
                lastActiveItemName = "";
            } else if (statusData.status === "idle") {
                 indicatorText = "Idle. Ready to start."; indicatorIcon = "info";
                 lastActiveItemName = "";
            } else if (statusData.status === "completed") {
                 indicatorText = "Migration Completed!"; indicatorIcon = "check-circle"; indicatorColor = "text-emerald-400";
                 lastActiveItemName = "";
            } else if (statusData.status === "error") {
                 indicatorText = "Error Occurred!"; indicatorIcon = "alert-triangle"; indicatorColor = "text-red-400";
                 lastActiveItemName = "";
            }

            if (indicatorText) {
                currentActionIndicator.classList.remove('hidden');
                currentActionIndicator.innerHTML = `<i data-lucide="${indicatorIcon}" class="mr-2 w-4 h-4 ${indicatorIcon === 'loader-2' ? 'animate-spin' : ''} ${indicatorColor}"></i> ${indicatorText}`;
            } else {
                currentActionIndicator.classList.add('hidden');
            }
        }
        if (window.lucide) window.lucide.createIcons();
    }

    function updateStatsUI(stats) {
        if (!statsContainer || !stats) {
            statsContainer.innerHTML = '<div class="text-gray-500 text-sm p-4 text-center">Stats not available yet...</div>';
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
                statDiv.className = 'p-4 rounded-xl border border-gray-800 bg-gray-900 bg-opacity-50 hover:bg-opacity-80 transition-all duration-300';
                statDiv.innerHTML = `
                    <div class="flex items-center mb-2">
                      <i data-lucide="${config.icon}" class="mr-2 ${config.colorClass} w-5 h-5"></i>
                      <h3 class="font-semibold text-gray-200 text-sm tracking-wide">${config.label}</h3>
                    </div>
                    <div class="ml-7">
                      <div class="flex justify-between text-xs text-gray-400 mb-1">
                        <span>Processed:</span>
                        <span class="font-bold text-gray-200">${completed} / ${total || '...'}</span>
                      </div>
                      <div class="w-full h-2 bg-gray-950 border border-gray-800 rounded-full overflow-hidden p-0.5">
                        <div 
                          class="h-full ${config.bgClass} rounded-full transition-all duration-500" 
                          style="width: ${percentage}%">
                        </div>
                      </div>
                      ${statData.current_item_name ? `<p class="text-[10px] text-gray-500 mt-1.5 truncate" title="${statData.current_item_name}">Current: <span class="font-mono text-gray-400">${statData.current_item_name}</span></p>` : '<p class="text-[10px] text-gray-500 mt-1.5">-</p>'}
                    </div>
                `;
                statsContainer.appendChild(statDiv);
            }
        });
        if (window.lucide) window.lucide.createIcons({context: statsContainer});
    }
    
    function updateLogUI(logEntries) {
        if (!logOutputContainer) return;
        
        if (logEntries.length === 0) {
            logOutputContainer.innerHTML = '<div class="text-gray-600 italic">Logs stream here in real-time as tasks complete...</div>';
            if (logCountElement) logCountElement.textContent = '0';
            return;
        }

        logOutputContainer.innerHTML = logEntries.map(log => {
            let colorClass = "text-gray-300"; 
            let icon = "info";
            let iconColor = "text-indigo-400";
            if (log.type === "warning") { colorClass = "text-yellow-300"; icon="alert-circle"; iconColor="text-yellow-400"; }
            if (log.type === "error") { colorClass = "text-red-400 font-medium"; icon="alert-triangle"; iconColor="text-red-400"; }
            return `<div class="${colorClass} mb-1 flex items-start font-mono"><i data-lucide="${icon}" class="w-3.5 h-3.5 mr-2 mt-0.5 flex-shrink-0 ${iconColor}"></i><span class="text-gray-600">[${log.timestamp}]&nbsp;</span><span>${log.message}</span></div>`;
        }).join('');
        
        if (logOutputContainer.scrollTop + logOutputContainer.clientHeight >= logOutputContainer.scrollHeight - 60) {
             logOutputContainer.scrollTop = logOutputContainer.scrollHeight;
        }
        if(logCountElement) logCountElement.textContent = logEntries.length;
        if (window.lucide) window.lucide.createIcons({context: logOutputContainer});
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
                                            data.status === "migrating_users" || 
                                            data.status === "migrating_groups" || 
                                            data.status === "migrating_projects";
                
                currentMigrationStatus = data.status; // Update global state
                
                updateButtonState(isCurrentlyMigrating, isCurrentlyMigrating ? 'Migration in Progress...' : 'Start Full Migration');
                updateMainStatusDisplay(data);
                updateStatsUI(data.stats);
                updateLogUI(data.logs);

                if (isCurrentlyMigrating) {
                    startAnimationLoop(); 
                } else {
                    if (pollingInterval) clearInterval(pollingInterval);
                    pollingInterval = null;
                    stopAnimationLoop();
                }
            })
            .catch(error => {
                console.error('Error fetching status:', error);
                updateMainStatusDisplay({status: "error", current_action: "Error fetching status from server.", error_message: error.message});
                if (pollingInterval) clearInterval(pollingInterval);
                pollingInterval = null;
                stopAnimationLoop();
                updateButtonState(false, 'Start Failed - Retry?');
            });
    }
    
    function checkLucideAndInit() {
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            console.log("Lucide is ready. Initializing UI.");
            window.lucide = lucide;
            window.lucide.createIcons(); // Initial full render of static icons
            fetchAndUpdateStatus(); // Fetch status immediately on load
            
            // Determine if polling should start based on initial status
            fetch(getStatusUrl)
                .then(r => r.json())
                .then(data => {
                    const isInitiallyMigrating = data.status === "running" || 
                                               data.status === "initializing" ||
                                               data.status === "migrating_users" ||
                                               data.status === "migrating_groups" ||
                                               data.status === "migrating_projects";
                    if (isInitiallyMigrating) {
                        currentMigrationStatus = data.status;
                        startAnimationLoop();
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