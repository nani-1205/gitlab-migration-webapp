document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elements ---
    const startMigrationButton = document.getElementById('startMigrationButton');
    const migrationButtonText = document.getElementById('migrationButtonText');
    const btnIcon = document.getElementById('btnIcon');
    
    const srcGroupsCnt = document.getElementById('srcGroupsCnt');
    const srcProjCnt = document.getElementById('srcProjCnt');
    const srcUsersCnt = document.getElementById('srcUsersCnt');
    const srcStatus = document.getElementById('srcStatus');
    const tgtStatus = document.getElementById('tgtStatus');
    
    const errorCountDisplay = document.getElementById('errorCountDisplay');
    const overallProgressBar = document.getElementById('overallProgressBar');
    const overallProgressPercent = document.getElementById('overallProgressPercent');
    const estTime = document.getElementById('estTime');
    const currentActionIndicatorText = document.getElementById('currentActionIndicatorText');
    
    const completedStatusDisplay = document.getElementById('completedStatusDisplay');
    const completedReportButtons = document.getElementById('completedReportButtons');
    const errorStatusDisplay = document.getElementById('errorStatusDisplay');
    const errorReportButtons = document.getElementById('errorReportButtons');
    const errorMessageText = document.getElementById('errorMessageText');

    const logOutputContainer = document.getElementById('logOutputContainer');
    const clearLogButton = document.getElementById('clearLogButton');

    const movingFilesContainer = document.getElementById('movingFilesContainer');
    const sourceNode = document.getElementById('sourceNode');
    const targetNode = document.getElementById('targetNode');
    const cablesSvg = document.getElementById('cablesSvg');

    // --- State & Configuration ---
    let pollingInterval = null;
    const pollingTime = 3000; 
    let animationIntervalId = null;
    let currentMigrationStatus = "idle";
    let cablesDrawn = false;
    const cables = [];

    const startMigrationUrl = "/start-migration"; 
    const getStatusUrl = "/get-status";

    // --- Event Listeners ---
    if (startMigrationButton) {
        startMigrationButton.addEventListener('click', handleStartMigration);
    }
    if (clearLogButton) {
        clearLogButton.addEventListener('click', () => {
            if (logOutputContainer) logOutputContainer.innerHTML = '<div class="text-gray-600 italic">[Terminal buffer cleared]</div>';
        });
    }

    window.addEventListener('resize', drawCables);

    // --- Dynamic Cables & Animation ---
    function drawCables() {
        if (!sourceNode || !targetNode || !cablesSvg) return;
        
        // Remove old paths
        cablesSvg.querySelectorAll('path').forEach(p => p.remove());
        cables.length = 0;

        const srcRect = sourceNode.getBoundingClientRect();
        const tgtRect = targetNode.getBoundingClientRect();
        const svgRect = cablesSvg.getBoundingClientRect();

        // Calculate connection points (right side of source, left side of target)
        const startX = (srcRect.right - svgRect.left) - 20;
        const startY = (srcRect.top - svgRect.top) + (srcRect.height / 2);
        
        const endX = (tgtRect.left - svgRect.left) + 20;
        const endY = (tgtRect.top - svgRect.top) + (tgtRect.height / 2);

        // Draw 4 distinct cables with varied control points
        const colors = ['rgba(16,185,129,0.4)', 'rgba(99,102,241,0.4)', 'rgba(168,85,247,0.4)', 'rgba(14,165,233,0.4)'];
        const offsetsY = [-30, -10, 10, 30];
        
        for (let i = 0; i < 4; i++) {
            const sy = startY + offsetsY[i];
            const ey = endY + offsetsY[i];
            
            // Control points for nice smooth curves
            const cp1X = startX + (endX - startX) * 0.4;
            const cp1Y = sy;
            const cp2X = startX + (endX - startX) * 0.6;
            const cp2Y = ey;

            const pathString = `M ${startX} ${sy} C ${cp1X} ${cp1Y}, ${cp2X} ${cp2Y}, ${endX} ${ey}`;
            cables.push(pathString);

            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', pathString);
            path.setAttribute('fill', 'none');
            path.setAttribute('stroke', colors[i]);
            path.setAttribute('stroke-width', i % 2 === 0 ? '4' : '3');
            path.setAttribute('filter', 'url(#glow)');
            if (currentMigrationStatus !== 'idle' && currentMigrationStatus !== 'completed' && currentMigrationStatus !== 'error') {
                path.classList.add('cable-pulse');
            }
            cablesSvg.appendChild(path);
        }
        cablesDrawn = true;
    }

    function toggleCablePulse(active) {
        if (!cablesSvg) return;
        cablesSvg.querySelectorAll('path').forEach(p => {
            if (active) p.classList.add('cable-pulse');
            else p.classList.remove('cable-pulse');
        });
    }

    function startAnimationLoop() {
        if (animationIntervalId) return;
        if (!cablesDrawn) drawCables();
        toggleCablePulse(true);
        animationIntervalId = setInterval(spawnPacket, 600); 
    }

    function stopAnimationLoop() {
        if (animationIntervalId) {
            clearInterval(animationIntervalId);
            animationIntervalId = null;
        }
        toggleCablePulse(false);
        if (movingFilesContainer) movingFilesContainer.innerHTML = ''; 
    }

    function spawnPacket() {
        if (!movingFilesContainer || cables.length === 0) return;
        if (movingFilesContainer.children.length >= 15) return; // limit

        const pathIndex = Math.floor(Math.random() * cables.length);
        const pathString = cables[pathIndex];
        
        const packetEl = document.createElement('div');
        packetEl.className = 'data-packet';

        // Select content based on phase
        let type = 'Project';
        let val = 'Mobile App';
        let typeClass = 'packet-project';

        if (currentMigrationStatus === 'migrating_users') {
            type = 'User'; val = ['Alex R.', 'Jane D.', 'Admin', 'DevUser'][Math.floor(Math.random() * 4)]; typeClass = 'packet-user';
        } else if (currentMigrationStatus === 'migrating_groups') {
            type = 'Group'; val = ['Dev Team', 'Marketing', 'Ops', 'Finance'][Math.floor(Math.random() * 4)]; typeClass = 'packet-group';
        } else if (currentMigrationStatus === 'migrating_projects') {
            type = 'Project'; val = ['Mobile App', 'Web Portal', 'Billing API', 'Runners Config'][Math.floor(Math.random() * 4)]; typeClass = 'packet-project';
        } else {
            type = 'Config'; val = 'settings.yml'; typeClass = 'packet-config';
        }

        packetEl.classList.add(typeClass);
        packetEl.innerHTML = `
            <div class="packet-type">${type}:</div>
            <div class="packet-value">${val}</div>
        `;

        movingFilesContainer.appendChild(packetEl);

        // Animate using Web Animations API and offset-path
        packetEl.style.offsetPath = `path('${pathString}')`;
        packetEl.style.offsetRotate = "0deg"; // Keep text upright

        const animation = packetEl.animate([
            { offsetDistance: '0%', opacity: 0, transform: 'scale(0.5)' },
            { offsetDistance: '15%', opacity: 1, transform: 'scale(1)' },
            { offsetDistance: '85%', opacity: 1, transform: 'scale(1)' },
            { offsetDistance: '100%', opacity: 0, transform: 'scale(0.5)' }
        ], {
            duration: 2500 + Math.random() * 1000,
            easing: 'cubic-bezier(0.4, 0.0, 0.2, 1)',
            fill: 'forwards'
        });

        animation.onfinish = () => packetEl.remove();
    }

    // --- Core Logic ---
    function handleStartMigration() {
        if (startMigrationButton.disabled) return;

        updateButtonState(true, 'Initializing...');
        completedStatusDisplay.classList.add('hidden');
        errorStatusDisplay.classList.add('hidden');
        if(errorMessageText) errorMessageText.textContent = "";

        currentMigrationStatus = 'initializing';
        startAnimationLoop();

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
                    updateButtonState(false, 'Pause / Cancel'); // Mockup text
                    errorStatusDisplay.classList.remove('hidden');
                }
            })
            .catch(error => {
                console.error('Error starting migration:', error);
                stopAnimationLoop();
                updateButtonState(false, 'Pause / Cancel');
                errorStatusDisplay.classList.remove('hidden');
            });
    }

    function updateButtonState(isMigrating, textContent) {
        if (!startMigrationButton || !migrationButtonText) return;
        migrationButtonText.textContent = textContent;
        if (btnIcon) btnIcon.setAttribute('data-lucide', isMigrating ? 'pause' : 'play');
        
        // Match mockup styling
        startMigrationButton.className = isMigrating ? 
            "bg-indigo-900 text-indigo-300 px-6 py-2 rounded-lg text-sm font-semibold tracking-wide transition-all flex items-center border border-indigo-700 opacity-80 cursor-not-allowed" :
            "bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-2 rounded-lg text-sm font-semibold tracking-wide shadow-[0_0_15px_rgba(99,102,241,0.4)] transition-all flex items-center border border-indigo-500";
        startMigrationButton.disabled = isMigrating;
        if (window.lucide) window.lucide.createIcons({elements: [startMigrationButton]});
    }
    
    function updateMainStatusDisplay(data) {
        if (data.status === "completed") {
            completedStatusDisplay.classList.remove('hidden');
            if (completedReportButtons && data.stats?.projects?.failed > 0) completedReportButtons.classList.remove('hidden');
            else if (completedReportButtons) completedReportButtons.classList.add('hidden');
            if (currentActionIndicatorText) currentActionIndicatorText.textContent = "Migration finished successfully.";
        } else if (data.status === "error") {
            errorStatusDisplay.classList.remove('hidden');
            if (errorMessageText) errorMessageText.textContent = data.error_message || "Unknown error";
            if (errorReportButtons && data.stats?.projects?.failed > 0) errorReportButtons.classList.remove('hidden');
            else if (errorReportButtons) errorReportButtons.classList.add('hidden');
            if (currentActionIndicatorText) currentActionIndicatorText.textContent = "Migration halted due to error.";
        } else {
            completedStatusDisplay.classList.add('hidden');
            errorStatusDisplay.classList.add('hidden');
            if (currentActionIndicatorText) currentActionIndicatorText.textContent = data.current_action || "Working...";
        }

        // Update server stats in the cubes
        if (data.stats) {
            if (srcGroupsCnt) srcGroupsCnt.textContent = data.stats.groups.completed || '0';
            if (srcProjCnt) srcProjCnt.textContent = data.stats.projects.completed || '0';
            if (srcUsersCnt) srcUsersCnt.textContent = data.stats.users.completed || '0';
            if (errorCountDisplay) {
                const totalFailed = (data.stats.users.failed || 0) + (data.stats.groups.failed || 0) + (data.stats.projects.failed || 0);
                errorCountDisplay.textContent = totalFailed;
            }
        }

        if (data.metrics && data.stats) {
            const avgSpeedDisplay = document.getElementById('avgSpeedDisplay');
            const avgSpeedBar = document.getElementById('avgSpeedBar');
            const dataFlowingDisplay = document.getElementById('dataFlowingDisplay');
            const dataFlowingBar = document.getElementById('dataFlowingBar');
            const filesSyncedDisplay = document.getElementById('filesSyncedDisplay');
            const filesSyncedBar = document.getElementById('filesSyncedBar');

            if (avgSpeedDisplay) avgSpeedDisplay.textContent = data.metrics.avg_speed_mb_s + " MB/s";
            
            let dataFlowingStr = data.metrics.data_flowing_bytes + " Bytes";
            if (data.metrics.data_flowing_bytes > 1024*1024*1024) dataFlowingStr = (data.metrics.data_flowing_bytes / (1024*1024*1024)).toFixed(2) + " GB";
            else if (data.metrics.data_flowing_bytes > 1024*1024) dataFlowingStr = (data.metrics.data_flowing_bytes / (1024*1024)).toFixed(1) + " MB";
            else if (data.metrics.data_flowing_bytes > 1024) dataFlowingStr = (data.metrics.data_flowing_bytes / 1024).toFixed(1) + " KB";
            if (dataFlowingDisplay) dataFlowingDisplay.textContent = dataFlowingStr;

            const totalItems = (data.stats.users.total || 0) + (data.stats.groups.total || 0) + (data.stats.projects.total || 0);
            const completedItems = (data.stats.users.completed || 0) + (data.stats.groups.completed || 0) + (data.stats.projects.completed || 0);
            
            if (filesSyncedDisplay) filesSyncedDisplay.textContent = completedItems;

            if (avgSpeedBar) {
                // assume 100 MB/s is "max" for visual bar
                let speedPct = Math.min(100, Math.max(0, (data.metrics.avg_speed_mb_s / 100) * 100));
                if (data.status === 'idle') speedPct = 0;
                avgSpeedBar.style.width = speedPct + "%";
            }
            if (dataFlowingBar && filesSyncedBar) {
                let itemPct = totalItems > 0 ? (completedItems / totalItems) * 100 : 0;
                if (data.status === 'idle') itemPct = 0;
                dataFlowingBar.style.width = itemPct + "%";
                filesSyncedBar.style.width = itemPct + "%";
            }
        }
        
        let overallProgress = 0;
        if (data.status === "migrating_users") overallProgress = Math.round(((data.stats.users.completed||0) / Math.max(1, data.stats.users.total||1)) * 10);
        else if (data.status === "migrating_groups") overallProgress = 10 + Math.round(((data.stats.groups.completed||0) / Math.max(1, data.stats.groups.total||1)) * 20);
        else if (data.status === "migrating_projects") overallProgress = 30 + Math.round(((data.stats.projects.completed||0) / Math.max(1, data.stats.projects.total||1)) * 70);
        else if (data.status === "completed") overallProgress = 100;
        else if (["initializing", "running"].includes(data.status)) overallProgress = 2;

        if (overallProgressBar && overallProgressPercent) {
            overallProgressBar.style.width = `${overallProgress}%`;
            overallProgressPercent.textContent = `${overallProgress}% Complete`;
        }
        if (estTime) estTime.textContent = overallProgress > 0 && overallProgress < 100 ? "Calculating..." : (overallProgress === 100 ? "Done" : "Pending");
    }

    function updateLogUI(logEntries) {
        if (!logOutputContainer) return;
        if (logEntries.length === 0) return;

        const html = logEntries.map(log => {
            let colorClass = "text-[#8fa2b3]"; 
            let levelLabel = "INFO";
            let levelColor = "text-indigo-400";
            if (log.type === "warning") { colorClass = "text-yellow-300"; levelLabel = "WARN"; levelColor="text-yellow-400"; }
            if (log.type === "error") { colorClass = "text-red-400 font-medium"; levelLabel = "DEBUG"; levelColor="text-red-500"; } // Mockup shows DEBUG in red/teal, using red for error here
            
            // Format like mockup: [2023-10-27 14:32:15] DEBUG Syncing repo...
            return `<div><span class="text-gray-600">[${log.timestamp}]</span> <span class="${levelColor} font-bold">${levelLabel}</span> <span class="${colorClass}">${log.message}</span></div>`;
        }).join('');
        
        const isScrolledToBottom = logOutputContainer.scrollHeight - logOutputContainer.clientHeight <= logOutputContainer.scrollTop + 20;
        logOutputContainer.innerHTML = html;
        if (isScrolledToBottom) logOutputContainer.scrollTop = logOutputContainer.scrollHeight;
    }
    
    function fetchAndUpdateStatus() {
        fetch(getStatusUrl)
            .then(r => { if(!r.ok) throw new Error(); return r.json(); })
            .then(data => {
                const isRunning = ["running", "initializing", "migrating_users", "migrating_groups", "migrating_projects"].includes(data.status);
                currentMigrationStatus = data.status;
                
                updateButtonState(isRunning, isRunning ? 'Pause / Cancel' : 'Start / Resume');
                updateMainStatusDisplay(data);
                updateLogUI(data.logs);

                if (isRunning) {
                    startAnimationLoop(); 
                } else {
                    if (pollingInterval) clearInterval(pollingInterval);
                    pollingInterval = null;
                    stopAnimationLoop();
                }
            })
            .catch(e => {
                console.error(e);
                if (pollingInterval) clearInterval(pollingInterval);
                pollingInterval = null;
                stopAnimationLoop();
            });
    }
    
    // Init
    setTimeout(() => {
        if (window.lucide) window.lucide.createIcons();
        drawCables();
        fetchAndUpdateStatus();
    }, 100);
});