    // ===== State =====
    let allTasks = [];
    let currentFilter = 'all';
    let currentGoalFilter = 'all';
    let shouldCollapseGoals = false;
    let currentView = 'dashboard';

    let refreshCountdown = 15;
    let refreshInterval = null;
    let isRefreshing = false;

    const chartColors = ['#58a6ff','#3fb950','#d29922','#f85149','#bc8cff','#39d2c0','#ff7b72','#79c0ff','#ffa657','#a5d6ff'];
    const L1_TOOLS = ['create_goal','update_goal','delete_goal','get_goal','list_goals','create_tasks','claim_task','report_task_result','release_task','get_task_detail','update_task','list_tasks','update_task_progress','save_checkpoint','get_task_context','get_global_rules','get_artifact','search_context','get_skill','list_skills','report_experience','get_dashboard','get_health_check'];
    const L2_TOOLS = ['get_memory_status','create_skill','update_skill','get_experiences','approve_evolution','trigger_evolution','snapshot_agent','get_safety_report','rollback_to_archive'];

    // ===== Init =====
    document.addEventListener('DOMContentLoaded', () => {
        updateClock();
        setInterval(updateClock, 1000);
        loadDashboardData();
        startAutoRefresh();
    });

    // ===== Live Clock =====
    function updateClock() {
        const now = new Date();
        document.getElementById('liveClock').textContent = now.toLocaleTimeString('zh-CN', {hour12:false});
    }

    // ===== View Switching (SPA) =====
    function switchView(view, btn) {
        if (currentView === view) return;
        currentView = view;
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        const target = document.getElementById('view-' + view);
        if (target) {
            target.classList.add('active');
            // 重新触发动画
            target.style.animation = 'none';
            target.offsetHeight;
            target.style.animation = '';
        }
        // 切换到修复经验页时加载数据
        if (view === 'fixexp') loadFixExpData();
        // 切换到恢复链路页时加载数据
        if (view === 'recovery') loadRecoveryData();
        // 切换到吐槽墙时加载数据
        if (view === 'complaints') loadComplaintsData();
        // 切换到任务队列时加载数据
        if (view === 'tasks') loadTaskView();
        // 切换到流程视图时加载数据
        if (view === 'projects') loadProjects();
        // 切换到Skills视图时加载数据
        if (view === 'skills') loadSkillsView();
    }

    // ===== Toast Notifications =====
    function showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        const toast = document.createElement('div');
        toast.className = 'toast ' + type;
        const icons = {success:'✅', error:'❌', info:'ℹ️'};
        toast.innerHTML = (icons[type] || 'ℹ️') + ' ' + message;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 3500);
    }

    // ===== Auto Refresh =====
    function startAutoRefresh() {
        refreshCountdown = 15;
        if (refreshInterval) clearInterval(refreshInterval);
        refreshInterval = setInterval(() => {
            refreshCountdown--;
            document.getElementById('refreshTimer').textContent = refreshCountdown + 's';
            if (refreshCountdown <= 0) {
                refreshCountdown = 15;
                refreshAll();
            }
        }, 1000);
    }

    function refreshAll() {
        if (isRefreshing) return;
        isRefreshing = true;
        const dot = document.getElementById('refreshDot');
        dot.classList.add('loading');
        Promise.all([
            loadDashboardData(),
            loadHealthData()
        ]).finally(() => {
            isRefreshing = false;
            dot.classList.remove('loading');
        });
    }

    // ===== Dashboard Data =====
    function loadDashboardData() {
        return fetch('/api/dashboard')
            .then(r => r.json())
            .then(data => {
                if (data.error) return;
                animateNumber('card-active-goals', data.active_goals || 0);
                animateNumber('card-total-tasks', data.total_tasks || 0);
                animateNumber('card-completed-tasks', data.completed_tasks || 0);
                animateNumber('card-skill-count', data.skill_count || 0);
                el('card-goals-sub').textContent = '总目标: ' + (data.total_goals || 0);
                el('card-task-sub').textContent = '待认领: ' + (data.pending_tasks || 0) + ' / 运行中: ' + (data.running_tasks || 0);
                el('card-failed-sub').textContent = '失败: ' + (data.failed_tasks || 0) + ' / 通过率: ' + (data.pass_rate || '0%');
                el('card-evo-sub').textContent = '进化次数: ' + (data.evolution_count || 0);

                // 任务状态分布
                animateNumber('stat-pending', data.pending_tasks || 0);
                animateNumber('stat-running', data.running_tasks || 0);
                animateNumber('stat-completed', data.completed_tasks || 0);
                animateNumber('stat-failed', data.failed_tasks || 0);
                animateNumber('stat-blocked', data.blocked_tasks || 0);
                animateNumber('stat-interrupted', data.interrupted_tasks || 0);
                animateNumber('stat-review', data.review_tasks || 0);

                // 经验与进化
                animateNumber('stat-pos-exp', data.positive_exp || 0);
                animateNumber('stat-neg-exp', data.negative_exp || 0);
                animateNumber('stat-evo-count', data.evolution_count || 0);
                el('stat-best-score').textContent = (data.best_score || 0).toFixed(1);
            })
            .catch(() => {});
    }

    // ===== Health Check Data =====
    function loadHealthData() {
        return fetch('/api/health')
            .then(r => r.json())
            .then(checks => {
                if (!Array.isArray(checks)) return;
                const tbody = el('healthCheckBody');
                if (!tbody) return;
                const statusMap = {
                    'healthy': '<span class="badge badge-green">✓ 健康</span>',
                    'warning': '<span class="badge badge-yellow">⚠ 警告</span>',
                    'error': '<span class="badge badge-red">✗ 异常</span>',
                    'degraded': '<span class="badge badge-orange">↓ 退化</span>'
                };
                tbody.innerHTML = checks.map(c => {
                    const badge = statusMap[c.Status] || '<span class="badge badge-gray">' + esc(c.Status) + '</span>';
                    return '<tr><td><strong>' + esc(c.Name) + '</strong></td><td>' + badge + '</td><td style="color:var(--text-muted);font-size:12px;">' + esc(c.Detail) + '</td></tr>';
                }).join('');
            })
            .catch(() => {
                const tbody = el('healthCheckBody');
                if (tbody) tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--text-dimmed);">获取失败</td></tr>';
            });
    }

    // ===== Animated Number =====
    function animateNumber(id, targetVal) {
        const elem = el(id);
        if (!elem) return;
        const current = parseInt(elem.textContent) || 0;
        if (current === targetVal) { elem.textContent = targetVal; return; }
        const diff = targetVal - current;
        const steps = Math.min(Math.abs(diff), 20);
        const stepVal = diff / steps;
        let step = 0;
        const interval = setInterval(() => {
            step++;
            if (step >= steps) {
                elem.textContent = targetVal;
                clearInterval(interval);
            } else {
                elem.textContent = Math.round(current + stepVal * step);
            }
        }, 30);
    }

    // ===== Tool Matrix =====
    function renderToolMatrix() {
        el('l1Tools').innerHTML = L1_TOOLS.map(t => '<span class="tool-badge l1">'+t+'</span>').join('');
        el('l2Tools').innerHTML = L2_TOOLS.map(t => '<span class="tool-badge l2">'+t+'</span>').join('') + '<span class="tool-badge" style="background:var(--border-light);color:var(--text-muted);border:1px solid transparent;">+ get_extended_tools</span>';
    }

    // ===== Task Modal =====
    function openTaskModal() {
        el('taskModal').classList.add('active');
        fetchTasks();
    }

    function closeTaskModal() {
        el('taskModal').classList.remove('active');
    }

    el('taskModal').addEventListener('click', function(e) { if (e.target === this) closeTaskModal(); });
    document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeTaskModal(); });

    function fetchTasks() {
        el('taskModalBody').innerHTML = '<div class="task-empty">加载中...</div>';
        fetch('/api/tasks')
            .then(r => r.json())
            .then(data => { allTasks = data || []; renderTasks(); taskViewData = data || []; renderTaskView(); })
            .catch(err => { el('taskModalBody').innerHTML = '<div class="task-empty">获取失败: '+err.message+'</div>'; });
    }

    function filterTasks(status, btn) {
        currentFilter = status;
        shouldCollapseGoals = false;
        el('taskFilters').querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderTasks();
    }

    function filterGoals(goalStatus, btn) {
        currentGoalFilter = goalStatus;
        shouldCollapseGoals = true;
        el('goalFilters').querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderTasks();
    }

    function getStatusBadge(status) {
        const map = {
            'pending':'<span class="badge badge-yellow">⏳ 待认领</span>',
            'running':'<span class="badge badge-blue">🔄 运行中</span>',
            'completed':'<span class="badge badge-green">✅ 完成</span>',
            'failed':'<span class="badge badge-red">❌ 失败</span>',
            'blocked':'<span class="badge badge-gray">🚫 阻塞</span>',
            'interrupted':'<span class="badge badge-orange">⚡ 中断</span>',
            'review':'<span class="badge badge-purple">🔍 审查中</span>'
        };
        return map[status] || '<span class="badge badge-gray">'+status+'</span>';
    }

    // 可编辑的状态下拉选择器
    function getStatusSelect(taskId, currentStatus) {
        const statuses = ['pending','running','completed','failed','blocked','interrupted','review'];
        const labels = {pending:'⏳ 待认领',running:'🔄 运行中',completed:'✅ 完成',failed:'❌ 失败',blocked:'🚫 阻塞',interrupted:'⚡ 中断',review:'🔍 审查中'};
        let opts = '';
        statuses.forEach(s => {
            opts += '<option value="'+s+'"'+(s===currentStatus?' selected':'')+'>'+labels[s]+'</option>';
        });
        return '<select class="status-select s-'+currentStatus+'" onchange="changeTaskStatus(\''+esc(taskId)+'\',this.value,this)" title="点击修改状态">'+opts+'</select>';
    }

    function changeTaskStatus(taskId, newStatus, selectEl) {
        fetch('/api/tasks/update-status', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({task_id:taskId, new_status:newStatus})})
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    showToast('状态修改失败: '+data.error, 'error');
                    fetchTasks(); // 回滚 UI
                } else {
                    showToast('已更新: '+taskId.substring(0,16)+'… → '+newStatus, 'success');
                    // 更新 select 样式
                    selectEl.className = 'status-select s-'+newStatus;
                    // 刷新数据
                    loadDashboardData();
                    // 重新加载任务列表以更新依赖树
                    fetchTasks();
                }
            })
            .catch(err => { showToast('状态修改失败: '+err.message, 'error'); fetchTasks(); });
    }

    // ===== Module Panels (独立看板) =====
    function openModulePanel(type) {
        const overlay = el('modulePanelOverlay');
        overlay.classList.add('active');
        el('modulePanelBody').innerHTML = '<div style="text-align:center;color:var(--text-dimmed);padding:40px;">加载中...</div>';

        switch(type) {
            case 'goals': loadGoalsPanel(); break;
            case 'completed': loadCompletedPanel(); break;
            case 'skills': loadSkillsPanel(); break;

            default: closeModulePanel();
        }
    }

    function closeModulePanel() {
        el('modulePanelOverlay').classList.remove('active');
    }
    el('modulePanelOverlay').addEventListener('click', function(e) { if (e.target === this) closeModulePanel(); });

    function loadGoalsPanel() {
        el('modulePanelTitle').innerHTML = '🎯 活跃目标看板';
        fetch('/api/goals').then(r=>r.json()).then(goals => {
            if (!goals || goals.length === 0) {
                el('modulePanelBody').innerHTML = '<div style="text-align:center;color:var(--text-dimmed);padding:40px;">暂无目标</div>';
                return;
            }
            let html = '';
            goals.forEach(g => {
                const total = g.total_tasks || 0;
                const completed = g.completed || 0;
                const pct = total > 0 ? (completed/total*100).toFixed(0) : 0;
                const pColor = pct >= 100 ? 'var(--green)' : pct >= 50 ? 'var(--yellow)' : 'var(--accent)';
                const status = g.status || 'pending';
                html += '<div class="goal-card">';
                html += '<div class="goal-card-top">';
                html += '<div class="goal-card-title">'+esc(g.title)+'</div>';
                html += '<div style="display:flex;align-items:center;gap:6px;">';
                // 状态切换按钮
                if (status === 'pending') {
                    html += '<button class="badge badge-green" style="cursor:pointer;border:none;font-size:11px;" onclick="updateGoalStatus(\''+esc(g.id)+'\',\'active\')" title="点击启动此目标">▶ 启动</button>';
                } else if (status === 'active') {
                    html += '<button class="badge badge-blue" style="cursor:pointer;border:none;font-size:11px;" onclick="updateGoalStatus(\''+esc(g.id)+'\',\'completed\')" title="点击标记完成">✓ 标记完成</button>';
                }
                html += getGoalStatusBadge(status);
                // 删除按钮
                html += '<button style="background:none;border:none;cursor:pointer;font-size:14px;padding:2px 4px;opacity:0.5;transition:opacity 0.2s;" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.5" onclick="deleteGoal(\''+esc(g.id)+'\',\''+esc(g.title)+'\')" title="删除此目标">🗑</button>';
                html += '</div></div>';
                html += '<div style="color:var(--text-muted);font-size:12px;margin-bottom:8px;">'+esc(g.description||'')+'</div>';
                html += '<div class="goal-card-meta">';
                html += '<span>📋 任务: '+completed+'/'+total+'</span>';
                html += '<span>📅 创建: '+(g.created_at||'—').substring(0,10)+'</span>';
                html += '<span>🔢 优先级: '+(g.priority||5)+'</span>';
                html += '</div>';
                html += '<div style="margin-top:8px;"><div class="progress-bar"><div class="progress-fill" style="width:'+pct+'%;background:'+pColor+';"></div></div>';
                html += '<div style="text-align:right;font-size:10px;color:var(--text-muted);margin-top:2px;">'+pct+'%</div></div>';
                html += '</div>';
            });
            el('modulePanelBody').innerHTML = html;
        }).catch(()=>{ el('modulePanelBody').innerHTML = '<div style="text-align:center;color:var(--red);padding:40px;">加载失败</div>'; });
    }

    // 更新目标状态
    function updateGoalStatus(goalId, newStatus) {
        fetch('/api/goals/update-status', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({goal_id:goalId, new_status:newStatus})})
            .then(r=>r.json())
            .then(data => {
                if (data.error) { showToast('状态修改失败: '+data.error, 'error'); return; }
                const labels = {active:'已启动',completed:'已完成',pending:'已暂停',cancelled:'已取消'};
                showToast('目标 '+labels[newStatus]+' ✓', 'success');
                loadGoalsPanel(); // 刷新面板
                loadDashboardData(); // 刷新首页统计
                fetchTasks(); // 刷新任务列表
            })
            .catch(err => showToast('操作失败: '+err.message, 'error'));
    }

    // 从任务列表中修改目标状态
    function updateGoalStatusFromTask(goalId, newStatus) {
        updateGoalStatus(goalId, newStatus);
    }

    // 全部审查：将目标下所有子任务和孙任务切换为 review 状态
    function reviewAllTasks(goalId, goalTitle) {
        if (!confirm('确认将目标「'+goalTitle+'」下所有任务切换为「🔍 审查中」状态？')) return;
        // 筛选该目标下所有已完成的任务
        var tasksToReview = allTasks.filter(function(t){ return t.goal_id === goalId && t.status === 'completed'; });
        if (tasksToReview.length === 0) {
            showToast('没有需要审查的任务', 'warning');
            return;
        }
        var total = tasksToReview.length;
        var done = 0;
        var failed = 0;
        showToast('正在批量切换 '+total+' 个任务为审查状态...', 'info');
        var promises = tasksToReview.map(function(t){
            return fetch('/api/tasks/update-status', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({task_id:t.id, new_status:'review'})
            }).then(function(r){ return r.json(); }).then(function(data){
                if (data.error) { failed++; } else { done++; }
            }).catch(function(){ failed++; });
        });
        Promise.all(promises).then(function(){
            if (failed > 0) {
                showToast('审查切换完成：成功 '+done+' 个，失败 '+failed+' 个', 'warning');
            } else {
                showToast('已将 '+done+' 个任务切换为审查状态 ✓', 'success');
            }
            fetchTasks(); // 刷新任务列表
            loadDashboardData(); // 刷新首页统计
        });
    }

    // 批量通过review：将目标下所有review状态任务标记为completed
    function reviewBatchPass(goalId, goalTitle) {
        if (!confirm('确认将目标「'+goalTitle+'」下所有审查中任务全部通过？')) return;
        var reviewer = '';
        fetch('/api/tasks/review-batch-pass', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({goal_id: goalId, reviewer: reviewer, comment: '批量通过'})
        }).then(function(r){ return r.json(); }).then(function(data){
            if (data.error) {
                showToast('批量通过失败: '+data.error, 'error');
            } else {
                showToast('已批量通过 '+data.updated_count+' 个任务 ✅', 'success');
                fetchTasks();
                loadDashboardData();
            }
        }).catch(function(err){ showToast('操作失败: '+err.message, 'error'); });
    }

    // 批量拒绝review：将目标下所有review状态任务标记为failed
    function reviewBatchFail(goalId, goalTitle) {
        var comment = prompt('请输入拒绝原因（可选）：', '');
        if (comment === null) return; // 用户取消
        if (!confirm('确认将目标「'+goalTitle+'」下所有审查中任务全部拒绝？')) return;
        fetch('/api/tasks/review-batch-fail', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({goal_id: goalId, reviewer: '', comment: comment || '批量拒绝'})
        }).then(function(r){ return r.json(); }).then(function(data){
            if (data.error) {
                showToast('批量拒绝失败: '+data.error, 'error');
            } else {
                showToast('已批量拒绝 '+data.updated_count+' 个任务 ❌', 'warning');
                fetchTasks();
                loadDashboardData();
            }
        }).catch(function(err){ showToast('操作失败: '+err.message, 'error'); });
    }

    // 删除目标
    function deleteGoal(goalId, goalTitle) {
        if (!confirm('确认删除目标「'+goalTitle+'」？\n⚠️ 将同时删除该目标下所有任务！')) return;
        fetch('/api/goals/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({goal_id:goalId, cascade:true})})
            .then(r=>r.json())
            .then(data => {
                if (data.error) { showToast('删除失败: '+data.error, 'error'); return; }
                showToast('目标已删除 ✓', 'success');
                loadGoalsPanel(); // 刷新面板
                loadDashboardData(); // 刷新首页统计
            })
            .catch(err => showToast('删除失败: '+err.message, 'error'));
    }

    function loadCompletedPanel() {
        el('modulePanelTitle').innerHTML = '✅ 完成统计看板';
        fetch('/api/dashboard').then(r=>r.json()).then(data => {
            const total = data.total_tasks || 0;
            const completed = data.completed_tasks || 0;
            const failed = data.failed_tasks || 0;
            const running = data.running_tasks || 0;
            const pending = data.pending_tasks || 0;
            const blocked = data.blocked_tasks || 0;
            const interrupted = data.interrupted_tasks || 0;
            let html = '<div class="stat-grid">';
            html += '<div class="stat-card"><div class="stat-label">总任务</div><div class="stat-value">'+total+'</div></div>';
            html += '<div class="stat-card"><div class="stat-label">已完成</div><div class="stat-value" style="color:var(--green);">'+completed+'</div></div>';
            html += '<div class="stat-card"><div class="stat-label">通过率</div><div class="stat-value" style="color:var(--accent);">'+(data.pass_rate||'0%')+'</div></div>';
            html += '<div class="stat-card"><div class="stat-label">失败</div><div class="stat-value" style="color:var(--red);">'+failed+'</div></div>';
            html += '<div class="stat-card"><div class="stat-label">运行中</div><div class="stat-value" style="color:var(--accent);">'+running+'</div></div>';
            html += '<div class="stat-card"><div class="stat-label">待认领</div><div class="stat-value" style="color:var(--yellow);">'+pending+'</div></div>';
            html += '<div class="stat-card"><div class="stat-label">阻塞</div><div class="stat-value" style="color:var(--text-muted);">'+blocked+'</div></div>';
            html += '<div class="stat-card"><div class="stat-label">中断</div><div class="stat-value" style="color:var(--orange);">'+interrupted+'</div></div>';
            html += '</div>';
            // 完成率进度大饼
            if (total > 0) {
                html += '<div style="margin-top:20px;text-align:center;"><div class="section-title">📈 总体完成进度</div>';
                const pct = (completed/total*100).toFixed(1);
                html += '<div style="display:inline-block;position:relative;width:160px;height:160px;">';
                html += '<svg viewBox="0 0 36 36" style="width:160px;height:160px;transform:rotate(-90deg);">';
                html += '<circle cx="18" cy="18" r="15.9" fill="none" stroke="var(--border-light)" stroke-width="3"/>';
                html += '<circle cx="18" cy="18" r="15.9" fill="none" stroke="var(--green)" stroke-width="3" stroke-dasharray="'+pct+' '+(100-pct)+'" stroke-linecap="round"/>';
                html += '</svg>';
                html += '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:28px;font-weight:800;color:var(--green);">'+pct+'%</div>';
                html += '</div></div>';
            }
            el('modulePanelBody').innerHTML = html;
        }).catch(()=>{ el('modulePanelBody').innerHTML = '<div style="text-align:center;color:var(--red);padding:40px;">加载失败</div>'; });
    }

    function loadSkillsPanel() {
        el('modulePanelTitle').innerHTML = '🧬 Skill 管理看板';
        fetch('/api/skills').then(r=>r.json()).then(skills => {
            // 顶部操作栏
            let html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">';
            html += '<div style="font-size:12px;color:var(--text-muted);">共 '+(skills?skills.length:0)+' 个 Skill</div>';
            html += '<button class="btn-primary" onclick="openSkillForm(\'create\')" style="font-size:12px;padding:6px 16px;">+ 新建 Skill</button>';
            html += '</div>';

            if (!skills || skills.length === 0) {
                html += '<div style="text-align:center;color:var(--text-dimmed);padding:40px;">暂无 Skill，点击上方按钮创建</div>';
                el('modulePanelBody').innerHTML = html;
                return;
            }
            skills.forEach(sk => {
                const m = sk.metrics || {};
                html += '<div class="skill-card">';
                html += '<div class="skill-card-top">';
                html += '<div style="display:flex;align-items:center;gap:8px;">';
                html += '<div class="skill-card-name">'+esc(sk.name)+'</div>';
                html += '<span class="badge badge-purple">v'+(sk.version||1)+'</span>';
                html += '</div>';
                html += '<div style="display:flex;align-items:center;gap:6px;">';
                html += '<button class="skill-edit-btn" onclick="openSkillForm(\'edit\',\''+esc(sk.name)+'\')" title="编辑">✏️ 编辑</button>';
                html += '<button class="skill-delete-btn" onclick="deleteSkill(\''+esc(sk.name)+'\')" title="删除">🗑 删除</button>';
                html += '</div>';
                html += '</div>';
                html += '<div style="color:var(--text-muted);font-size:12px;margin-bottom:6px;">'+esc(sk.description||'—')+'</div>';
                html += '<div class="skill-card-meta">';
                html += '<span>📏 规则: '+(sk.rules_count||m.rule_count||0)+'</span>';
                html += '<span>📊 使用: '+(m.usage_count||0)+' 次</span>';
                html += '<span>✅ 通过率: '+(m.pass_rate||'N/A')+'</span>';
                html += '<span>🔄 进化: '+(m.evolution_count||0)+' 次</span>';
                html += '<span>📅 更新: '+(sk.updated_at||'—').substring(0,10)+'</span>';
                html += '</div></div>';
            });
            el('modulePanelBody').innerHTML = html;
        }).catch(()=>{ el('modulePanelBody').innerHTML = '<div style="text-align:center;color:var(--red);padding:40px;">加载失败</div>'; });
    }

    // ===== Skill Form (创建/编辑) =====
    function openSkillForm(mode, skillName) {
        el('skillFormMode').value = mode;
        el('skillFormOrigName').value = skillName || '';

        if (mode === 'create') {
            el('skillFormTitle').innerHTML = '🧬 新建 Skill';
            el('skillFormSubmit').textContent = '创建 Skill';
            el('skillName').value = '';
            el('skillName').disabled = false;
            el('skillDesc').value = '';
            el('skillTags').value = '';
            el('skillRules').value = '';
            el('skillAntiPatterns').value = '';
            el('skillBestPractices').value = '';
            el('skillChecklist').value = '';
            el('skillTemplate').value = '';
            el('skillContextHints').value = '';
            el('skillFormOverlay').classList.add('active');
        } else {
            el('skillFormTitle').innerHTML = '✏️ 编辑 Skill: ' + skillName;
            el('skillFormSubmit').textContent = '保存修改';
            el('skillName').value = skillName;
            el('skillName').disabled = true;
            // 加载详情
            fetch('/api/skills/detail?name=' + encodeURIComponent(skillName))
                .then(r => r.json())
                .then(detail => {
                    if (detail.error) { showToast('加载失败: ' + detail.error, 'error'); return; }
                    el('skillDesc').value = detail.description || '';
                    el('skillTags').value = (detail.tags || []).join(', ');
                    const dna = detail.dna || {};
                    el('skillRules').value = (dna.rules || []).join('\n');
                    el('skillAntiPatterns').value = (dna.anti_patterns || []).join('\n');
                    el('skillBestPractices').value = (dna.best_practices || []).join('\n');
                    el('skillChecklist').value = (dna.checklist || []).join('\n');
                    el('skillTemplate').value = dna.template || '';
                    el('skillContextHints').value = (dna.context_hints || []).join('\n');
                    el('skillFormOverlay').classList.add('active');
                })
                .catch(err => showToast('加载 Skill 详情失败: ' + err.message, 'error'));
        }
    }

    function closeSkillForm() {
        el('skillFormOverlay').classList.remove('active');
    }
    el('skillFormOverlay').addEventListener('click', function(e) { if (e.target === this) closeSkillForm(); });

    // 文本框内容转数组（按行分割，去空行）
    function textToArray(text) {
        return text.split('\n').map(s => s.trim()).filter(s => s.length > 0);
    }

    function submitSkillForm() {
        const mode = el('skillFormMode').value;
        const name = el('skillName').value.trim();
        if (!name) { showToast('Skill 名称不能为空', 'error'); return; }
        if (mode === 'create' && !/^[a-z][a-z0-9_]*$/.test(name)) {
            showToast('名称格式错误：小写字母开头，仅含小写字母、数字、下划线', 'error');
            return;
        }

        const dna = {
            rules: textToArray(el('skillRules').value),
            anti_patterns: textToArray(el('skillAntiPatterns').value),
            best_practices: textToArray(el('skillBestPractices').value),
            checklist: textToArray(el('skillChecklist').value),
            template: el('skillTemplate').value.trim(),
            context_hints: textToArray(el('skillContextHints').value)
        };

        const tags = el('skillTags').value.split(',').map(s => s.trim()).filter(s => s);

        el('skillFormSubmit').disabled = true;
        el('skillFormSubmit').textContent = '提交中...';

        if (mode === 'create') {
            fetch('/api/skills/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name, description: el('skillDesc').value.trim(), dna, tags })
            })
            .then(r => r.json())
            .then(data => {
                if (data.error) { showToast('创建失败: ' + data.error, 'error'); return; }
                showToast('Skill「' + name + '」创建成功 ✓', 'success');
                closeSkillForm();
                loadSkillsPanel();
                loadDashboardData();
                if (currentView === 'skills') loadSkillsView();
            })
            .catch(err => showToast('创建失败: ' + err.message, 'error'))
            .finally(() => {
                el('skillFormSubmit').disabled = false;
                el('skillFormSubmit').textContent = '创建 Skill';
            });
        } else {
            fetch('/api/skills/update', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name: el('skillFormOrigName').value, fields: { description: el('skillDesc').value.trim(), dna, tags } })
            })
            .then(r => r.json())
            .then(data => {
                if (data.error) { showToast('更新失败: ' + data.error, 'error'); return; }
                showToast('Skill「' + name + '」已更新 ✓', 'success');
                closeSkillForm();
                loadSkillsPanel();
                if (currentView === 'skills') loadSkillsView();
            })
            .catch(err => showToast('更新失败: ' + err.message, 'error'))
            .finally(() => {
                el('skillFormSubmit').disabled = false;
                el('skillFormSubmit').textContent = '保存修改';
            });
        }
    }

    function deleteSkill(name) {
        if (!confirm('确认删除 Skill「' + name + '」？\n⚠️ 删除后不可恢复！')) return;
        fetch('/api/skills/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name })
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) { showToast('删除失败: ' + data.error, 'error'); return; }
            showToast('Skill「' + name + '」已删除 ✓', 'success');
            loadSkillsPanel();
            loadDashboardData();
        })
        .catch(err => showToast('删除失败: ' + err.message, 'error'));
    }

    // ===== Skills View (独立选项卡) =====
    var allSkillsData = [];
    var currentAuditSkillName = '';

    function loadSkillsView() {
        // 加载自动进化开关状态
        fetch('/api/config/skill-auto-evolution').then(r=>r.json()).then(data => {
            var toggle = document.getElementById('skillAutoEvoToggle');
            if (toggle) toggle.checked = data.enabled !== false;
        }).catch(function(){});

        // 加载Skills列表
        fetch('/api/skills').then(r=>r.json()).then(function(skills) {
            allSkillsData = skills || [];
            el('skillViewCount').textContent = '共 ' + allSkillsData.length + ' 个 Skill';
            renderSkillViewCards(allSkillsData);
        }).catch(function() {
            el('skillViewBody').innerHTML = '<div style="text-align:center;color:var(--red);padding:40px;grid-column:1/-1;">加载失败</div>';
        });
    }

    function renderSkillViewCards(skills) {
        if (!skills || skills.length === 0) {
            el('skillViewBody').innerHTML = '<div style="text-align:center;color:var(--text-dimmed);padding:60px;grid-column:1/-1;">暂无 Skill，点击右上角「+ 新建 Skill」创建</div>';
            return;
        }
        var html = '';
        skills.forEach(function(sk) {
            var m = sk.metrics || {};
            var passRate = m.pass_rate || '0';
            var passRateNum = parseFloat(passRate);
            var passColor = passRateNum >= 80 ? 'var(--green)' : passRateNum >= 50 ? 'var(--yellow)' : 'var(--red)';
            var healthBadge = '';
            var rulesCount = sk.rules_count || m.rule_count || 0;
            if (parseInt(rulesCount) > 15) {
                healthBadge = '<span class="badge badge-yellow" style="font-size:9px;padding:1px 6px;" title="规则数量较多">⚠️ 膨胀</span>';
            }

            html += '<div class="skill-view-card">';
            // 头部：名称 + 版本 + 健康标签
            html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">';
            html += '<div style="display:flex;align-items:center;gap:8px;">';
            html += '<span style="font-size:15px;font-weight:700;color:var(--purple);font-family:\'SF Mono\',\'Fira Code\',monospace;">'+esc(sk.name)+'</span>';
            html += '<span class="badge badge-purple" style="font-size:10px;">v'+(sk.version||1)+'</span>';
            html += healthBadge;
            html += '</div>';
            html += '<div style="display:flex;gap:6px;">';
            html += '<button class="skill-audit-btn" onclick="auditSkill(\''+esc(sk.name)+'\')" title="质量审核">🔍 审核</button>';
            html += '<button class="skill-audit-btn" onclick="evolveSkill(\''+esc(sk.name)+'\')" title="从经验中吸收进化" style="background:var(--green);color:#fff;border-color:var(--green);">🧬 进化</button>';
            html += '<button class="skill-edit-btn" onclick="openSkillForm(\'edit\',\''+esc(sk.name)+'\')" title="编辑">✏️ 编辑</button>';
            html += '<button class="skill-delete-btn" onclick="deleteSkillFromView(\''+esc(sk.name)+'\')" title="删除">🗑️</button>';
            html += '</div>';
            html += '</div>';
            // 描述
            html += '<div style="font-size:12px;color:var(--text-muted);margin-bottom:10px;line-height:1.5;max-height:36px;overflow:hidden;">'+esc(sk.description||'暂无描述')+'</div>';
            // 指标
            html += '<div style="display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--text-muted);padding-top:8px;border-top:1px solid var(--border-light);">';
            html += '<span title="规则数量">📏 规则 <b style="color:var(--text-secondary);">'+rulesCount+'</b></span>';
            html += '<span title="使用次数">📊 使用 <b style="color:var(--text-secondary);">'+(m.usage_count||0)+'</b>次</span>';
            html += '<span title="通过率">✅ 通过率 <b style="color:'+passColor+';">'+passRate+'%</b></span>';
            html += '<span title="进化次数">🔄 进化 <b style="color:var(--text-secondary);">'+(m.evolution_count||0)+'</b>次</span>';
            if (m.stale_rules && parseInt(m.stale_rules) > 0) {
                html += '<span title="陈旧规则">⏳ 陈旧 <b style="color:var(--orange);">'+m.stale_rules+'</b></span>';
            }
            html += '<span title="最后更新">📅 '+(sk.updated_at||'—').substring(0,10)+'</span>';
            html += '</div>';
            html += '</div>';
        });
        el('skillViewBody').innerHTML = html;
    }

    function filterSkillCards() {
        var keyword = (document.getElementById('skillSearchInput').value || '').toLowerCase().trim();
        if (!keyword) {
            renderSkillViewCards(allSkillsData);
            return;
        }
        var filtered = allSkillsData.filter(function(sk) {
            return (sk.name || '').toLowerCase().indexOf(keyword) >= 0 ||
                   (sk.description || '').toLowerCase().indexOf(keyword) >= 0;
        });
        renderSkillViewCards(filtered);
    }

    function deleteSkillFromView(name) {
        if (!confirm('确认删除 Skill「' + name + '」？\n⚠️ 删除后不可恢复！')) return;
        fetch('/api/skills/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: name })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { showToast('删除失败: ' + data.error, 'error'); return; }
            showToast('Skill「' + name + '」已删除 ✓', 'success');
            loadSkillsView();
            loadDashboardData();
        })
        .catch(function(err) { showToast('删除失败: ' + err.message, 'error'); });
    }

    function toggleSkillAutoEvolution() {
        var enabled = document.getElementById('skillAutoEvoToggle').checked;
        fetch('/api/config/skill-auto-evolution', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ enabled: enabled })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                showToast('设置失败: ' + data.error, 'error');
                document.getElementById('skillAutoEvoToggle').checked = !enabled; // 回滚
                return;
            }
            showToast('自动进化已' + (enabled ? '开启 ✅' : '关闭 ⛔'), enabled ? 'success' : 'info');
        })
        .catch(function(err) {
            showToast('设置失败: ' + err.message, 'error');
            document.getElementById('skillAutoEvoToggle').checked = !enabled;
        });
    }

    // ===== 吸收远程 Skill =====
    function openAbsorbSkill() {
        document.getElementById('absorbSkillAddr').value = '';
        document.getElementById('absorbSkillKeyword').value = '';
        document.getElementById('absorbSkillOverwrite').checked = false;
        document.getElementById('absorbSkillResult').style.display = 'none';
        document.getElementById('absorbSkillResult').innerHTML = '';
        document.getElementById('absorbSkillSubmitBtn').disabled = false;
        document.getElementById('absorbSkillSubmitBtn').textContent = '🔗 开始吸收';
        document.getElementById('absorbSkillOverlay').classList.add('active');
    }

    function closeAbsorbSkillModal() {
        document.getElementById('absorbSkillOverlay').classList.remove('active');
    }

    function submitAbsorbSkill() {
        var addr = document.getElementById('absorbSkillAddr').value.trim();
        if (!addr) { showToast('请输入远程 MCP Dashboard 地址', 'error'); return; }

        var keyword = document.getElementById('absorbSkillKeyword').value.trim();
        var overwrite = document.getElementById('absorbSkillOverwrite').checked;

        var btn = document.getElementById('absorbSkillSubmitBtn');
        btn.disabled = true;
        btn.textContent = '⏳ 吸收中...';

        var resultDiv = document.getElementById('absorbSkillResult');
        resultDiv.style.display = 'block';
        resultDiv.innerHTML = '<div style="text-align:center;color:var(--accent);padding:12px;"><span style="animation:spin 1s linear infinite;display:inline-block;">⏳</span> 正在连接远程实例并拉取 Skill 数据...</div>';

        fetch('/api/skills/absorb', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({remote_addr: addr, keyword: keyword, overwrite: overwrite})
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            btn.disabled = false;
            btn.textContent = '🔗 再次吸收';
            if (data.error) {
                resultDiv.innerHTML = '<div style="padding:12px;border-radius:var(--radius-xs);background:rgba(248,81,73,0.1);border-left:3px solid var(--red);"><span style="color:var(--red);font-weight:600;">❌ 吸收失败</span><div style="font-size:12px;color:var(--text-muted);margin-top:4px;">' + esc(data.error) + '</div></div>';
                return;
            }
            var html = '<div style="padding:12px;border-radius:var(--radius-xs);background:rgba(63,185,80,0.1);border-left:3px solid var(--green);">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
            html += '<span style="color:var(--green);font-weight:700;font-size:14px;">✅ 吸收完成</span>';
            html += '<span style="font-size:12px;color:var(--text-muted);">来源: ' + esc(data.remote_addr||addr) + '</span>';
            html += '</div>';
            html += '<div style="display:flex;gap:16px;font-size:13px;flex-wrap:wrap;">';
            html += '<span>📥 吸收: <b style="color:var(--green);">' + (data.absorbed||0) + '</b></span>';
            html += '<span>🔀 合并: <b style="color:var(--accent);">' + (data.merged||0) + '</b></span>';
            html += '<span>⏭ 跳过: <b style="color:var(--yellow);">' + (data.skipped||0) + '</b></span>';
            html += '<span>🔄 覆盖: <b style="color:var(--orange);">' + (data.overwritten||0) + '</b></span>';
            html += '<span>❌ 失败: <b style="color:var(--red);">' + (data.failed||0) + '</b></span>';
            html += '</div>';
            if (data.details && data.details.length > 0) {
                html += '<div style="font-size:11px;color:var(--text-muted);border-top:1px solid var(--border);padding-top:6px;margin-top:8px;max-height:120px;overflow-y:auto;">';
                data.details.forEach(function(d) {
                    var icon = d.status === 'absorbed' ? '✅' : d.status === 'merged' ? '🔀' : d.status === 'overwritten' ? '🔄' : d.status === 'skipped' ? '⏭' : '❌';
                    html += '<div>' + icon + ' ' + esc(d.name) + ' — ' + esc(d.status) + (d.reason ? ' (' + esc(d.reason) + ')' : '') + '</div>';
                });
                html += '</div>';
            }
            html += '</div>';
            resultDiv.innerHTML = html;

            // 刷新 Skill 列表
            loadSkillsView();
            loadDashboardData();
        })
        .catch(function(err) {
            btn.disabled = false;
            btn.textContent = '🔗 重试吸收';
            resultDiv.innerHTML = '<div style="padding:12px;border-radius:var(--radius-xs);background:rgba(248,81,73,0.1);border-left:3px solid var(--red);"><span style="color:var(--red);font-weight:600;">❌ 网络错误</span><div style="font-size:12px;color:var(--text-muted);margin-top:4px;">' + esc(err.message) + '</div></div>';
        });
    }

    // ===== Skill 进化（从经验中吸收进化）=====
    function evolveSkill(name) {
        if (!confirm('确认对 Skill "' + name + '" 执行经验吸收进化？\n\n这将分析所有相关经验，自动提炼规则/反模式/最佳实践并更新 Skill DNA。低影响变更会自动应用，高影响变更进入审批队列。')) {
            return;
        }
        // 显示全局 loading toast
        showToast('⏳ 正在对 "' + name + '" 执行经验吸收进化...', 'info', 10000);

        fetch('/api/skills/evolve', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: name, auto_apply: true })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                showToast('❌ 进化失败: ' + data.error, 'error');
                return;
            }
            // 构建进化结果摘要
            var summary = data.summary || '';
            var applied = data.proposals_applied || 0;
            var pending = data.proposals_pending || 0;
            var analyzed = data.experiences_analyzed || 0;
            var patterns = data.patterns_detected || 0;
            var dupRemoved = data.duplicates_removed || 0;
            var staleRemoved = data.stale_rules_removed || 0;

            var msg = '🧬 进化完成！\n';
            msg += '• 分析经验: ' + analyzed + ' 条\n';
            msg += '• 检测模式: ' + patterns + ' 个\n';
            msg += '• 已应用提案: ' + applied + ' 个\n';
            msg += '• 待审批提案: ' + pending + ' 个\n';
            if (dupRemoved > 0 || staleRemoved > 0) {
                msg += '• 清理: 重复 ' + dupRemoved + ' / 陈旧 ' + staleRemoved + ' 条规则';
            }

            showToast(msg, applied > 0 ? 'success' : 'info', 8000);
            // 刷新 Skill 列表
            loadSkillsView();
        })
        .catch(function(err) {
            showToast('❌ 网络错误: ' + err.message, 'error');
        });
    }

    // ===== Skill 质量审核 =====
    function auditSkill(name) {
        currentAuditSkillName = name;
        document.getElementById('skillAuditTitle').textContent = '🔍 审核: ' + name;
        document.getElementById('skillAuditBody').innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-dimmed);">⏳ 正在审核 Skill DNA 质量...</div>';
        document.getElementById('skillAuditFixBtn').style.display = 'none';
        document.getElementById('skillAuditOverlay').classList.add('active');

        fetch('/api/skills/audit', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: name, auto_fix: false })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                document.getElementById('skillAuditBody').innerHTML = '<div style="text-align:center;color:var(--red);padding:40px;">审核失败: '+esc(data.error)+'</div>';
                return;
            }
            renderAuditResult(data);
        })
        .catch(function(err) {
            document.getElementById('skillAuditBody').innerHTML = '<div style="text-align:center;color:var(--red);padding:40px;">审核请求失败: '+esc(err.message)+'</div>';
        });
    }

    function renderAuditResult(data) {
        var healthColors = { healthy: 'var(--green)', needs_attention: 'var(--orange)', unhealthy: 'var(--red)' };
        var healthLabels = { healthy: '✅ 健康', needs_attention: '⚠️ 需关注', unhealthy: '❌ 不健康' };
        var healthColor = healthColors[data.overall_health] || 'var(--text-muted)';
        var healthLabel = healthLabels[data.overall_health] || data.overall_health;

        var html = '';
        // 概览
        html += '<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px;">';
        html += '<div style="flex:1;min-width:200px;padding:14px;background:var(--bg-tertiary);border-radius:var(--radius-xs);border-left:4px solid '+healthColor+';">';
        html += '<div style="font-size:12px;color:var(--text-muted);margin-bottom:4px;">整体健康度</div>';
        html += '<div style="font-size:18px;font-weight:700;color:'+healthColor+';">'+healthLabel+'</div>';
        html += '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">v'+esc(String(data.version||1))+' · '+esc(data.skill_name)+'</div>';
        html += '</div>';
        html += '<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:stretch;">';
        html += '<div style="padding:14px 18px;background:var(--bg-tertiary);border-radius:var(--radius-xs);text-align:center;min-width:70px;">';
        html += '<div style="font-size:20px;font-weight:700;color:var(--red);">'+data.critical_count+'</div>';
        html += '<div style="font-size:10px;color:var(--text-muted);">严重</div></div>';
        html += '<div style="padding:14px 18px;background:var(--bg-tertiary);border-radius:var(--radius-xs);text-align:center;min-width:70px;">';
        html += '<div style="font-size:20px;font-weight:700;color:var(--orange);">'+data.warning_count+'</div>';
        html += '<div style="font-size:10px;color:var(--text-muted);">警告</div></div>';
        html += '<div style="padding:14px 18px;background:var(--bg-tertiary);border-radius:var(--radius-xs);text-align:center;min-width:70px;">';
        html += '<div style="font-size:20px;font-weight:700;color:var(--accent);">'+data.info_count+'</div>';
        html += '<div style="font-size:10px;color:var(--text-muted);">信息</div></div>';
        html += '</div></div>';

        // DNA 统计
        if (data.dna_stats) {
            html += '<div style="padding:10px 14px;background:var(--bg-tertiary);border-radius:var(--radius-xs);margin-bottom:14px;display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:var(--text-muted);">';
            html += '<span>📏 Rules: <b>'+data.dna_stats.rules+'</b></span>';
            html += '<span>🚫 Anti-Patterns: <b>'+data.dna_stats.anti_patterns+'</b></span>';
            html += '<span>✅ Best Practices: <b>'+data.dna_stats.best_practices+'</b></span>';
            html += '<span>📝 Checklist: <b>'+data.dna_stats.checklist+'</b></span>';
            html += '</div>';
        }

        // 建议
        if (data.recommendation) {
            html += '<div style="padding:10px 14px;background:rgba(88,166,255,0.06);border-radius:var(--radius-xs);border-left:3px solid var(--accent);margin-bottom:14px;font-size:12px;color:var(--text-secondary);">💡 '+esc(data.recommendation)+'</div>';
        }

        // 问题列表
        var issues = data.issues || [];
        if (issues.length > 0) {
            html += '<div style="font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;">📋 发现 '+issues.length+' 个问题</div>';
            var hasFixable = false;
            issues.forEach(function(iss, idx) {
                var severityIcons = { critical: '🔴', warning: '🟡', info: '🔵' };
                var severityColors = { critical: 'var(--red)', warning: 'var(--orange)', info: 'var(--accent)' };
                var icon = severityIcons[iss.severity] || '⚪';
                var color = severityColors[iss.severity] || 'var(--text-muted)';
                if (iss.auto_fixable && !iss.fixed) hasFixable = true;
                html += '<div style="padding:10px 14px;background:var(--bg-tertiary);border-radius:var(--radius-xs);margin-bottom:6px;border-left:3px solid '+color+';">';
                html += '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">';
                html += '<div style="font-size:12px;color:var(--text-secondary);line-height:1.5;">'+icon+' '+esc(iss.description)+'</div>';
                html += '<div style="display:flex;gap:4px;flex-shrink:0;">';
                if (iss.auto_fixable) html += '<span class="badge badge-yellow" style="font-size:9px;padding:1px 5px;">可修复</span>';
                if (iss.fixed) html += '<span class="badge badge-green" style="font-size:9px;padding:1px 5px;">已修复</span>';
                html += '<span class="badge badge-gray" style="font-size:9px;padding:1px 5px;">'+esc(iss.category)+'</span>';
                html += '</div></div>';
                if (iss.suggestion) {
                    html += '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">💡 '+esc(iss.suggestion)+'</div>';
                }
                html += '</div>';
            });
            if (hasFixable) {
                document.getElementById('skillAuditFixBtn').style.display = 'inline-block';
            }
        } else {
            html += '<div style="text-align:center;color:var(--green);padding:20px;font-size:14px;font-weight:600;">🎉 未发现任何问题，Skill DNA 质量优秀！</div>';
        }

        // 自动修复结果
        if (data.auto_fixed > 0) {
            html += '<div style="padding:10px 14px;background:rgba(63,185,80,0.1);border-radius:var(--radius-xs);border-left:3px solid var(--green);margin-top:12px;font-size:12px;color:var(--green);font-weight:600;">🔧 自动修复了 '+data.auto_fixed+' 个问题</div>';
        }

        document.getElementById('skillAuditBody').innerHTML = html;
    }

    function auditSkillAutoFix() {
        if (!currentAuditSkillName) return;
        document.getElementById('skillAuditFixBtn').disabled = true;
        document.getElementById('skillAuditFixBtn').textContent = '修复中...';

        fetch('/api/skills/audit', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: currentAuditSkillName, auto_fix: true })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('skillAuditFixBtn').disabled = false;
            document.getElementById('skillAuditFixBtn').textContent = '🔧 自动修复';
            if (data.error) {
                showToast('自动修复失败: ' + data.error, 'error');
                return;
            }
            if (data.auto_fixed > 0) {
                showToast('已自动修复 ' + data.auto_fixed + ' 个问题 ✓', 'success');
            } else {
                showToast('没有可自动修复的问题', 'info');
            }
            renderAuditResult(data);
            loadSkillsView(); // 刷新列表
        })
        .catch(function(err) {
            document.getElementById('skillAuditFixBtn').disabled = false;
            document.getElementById('skillAuditFixBtn').textContent = '🔧 自动修复';
            showToast('修复请求失败: ' + err.message, 'error');
        });
    }

    function closeSkillAudit() {
        document.getElementById('skillAuditOverlay').classList.remove('active');
    }

    function getGoalStatusBadge(status) {
        const map = {
            'pending':'<span class="badge badge-yellow" style="font-size:10px;">待启动</span>',
            'active':'<span class="badge badge-blue" style="font-size:10px;">进行中</span>',
            'completed':'<span class="badge badge-green" style="font-size:10px;">已完成</span>',
            'cancelled':'<span class="badge badge-gray" style="font-size:10px;">已取消</span>'
        };
        return map[status] || '<span class="badge badge-gray" style="font-size:10px;">'+(status||'未知')+'</span>';
    }

    function getProgressColor(p) { return p >= 100 ? 'p-green' : p >= 50 ? 'p-yellow' : 'p-blue'; }

    function renderTasks() {
        const filtered = currentFilter === 'all' ? allTasks : allTasks.filter(t => t.status === currentFilter);
        const counts = {};
        allTasks.forEach(t => { counts[t.status] = (counts[t.status]||0)+1; });

        // 统计目标组状态计数
        const goalStatusCounts = {};
        const seenGoals = {};
        allTasks.forEach(t => {
            const gid = t.goal_id || '__ungrouped__';
            if (!seenGoals[gid]) {
                seenGoals[gid] = true;
                const gs = t.goal_status || '';
                if (gs) goalStatusCounts[gs] = (goalStatusCounts[gs] || 0) + 1;
            }
        });

        // 更新目标组筛选按钮计数
        el('goalFilters').querySelectorAll('.filter-btn').forEach(btn => {
            const gs = btn.dataset.goalStatus;
            if (gs === 'all') {
                btn.textContent = '全部 (' + Object.values(goalStatusCounts).reduce((a,b) => a+b, 0) + ')';
                return;
            }
            const c = goalStatusCounts[gs] || 0;
            const labels = {active:'▶ 进行中',pending:'⏸ 暂停',completed:'✅ 已完成',cancelled:'✕ 已取消'};
            btn.textContent = (labels[gs]||gs) + ' (' + c + ')';
        });

        el('taskCountInfo').textContent = '（共 '+allTasks.length+' 个任务'+(currentFilter !== 'all' ? '，筛选 '+filtered.length+' 个' : '')+'）';

        // 更新任务筛选按钮计数
        el('taskFilters').querySelectorAll('.filter-btn').forEach(btn => {
            const st = btn.dataset.status;
            if (st === 'all') return;
            const c = counts[st] || 0;
            const labels = {pending:'⏳ 待认领',running:'🔄 运行中',completed:'✅ 已完成',failed:'❌ 失败',blocked:'🚫 阻塞',interrupted:'⚡ 中断',review:'🔍 审查中'};
            btn.textContent = (labels[st]||st) + ' (' + c + ')';
        });

        if (filtered.length === 0) {
            el('taskModalBody').innerHTML = '<div class="task-empty">暂无任务</div>';
            return;
        }

        // 按 Goal 分组
        const groups = {}, order = [];
        filtered.forEach(t => {
            const gid = t.goal_id || '__ungrouped__';
            if (!groups[gid]) {
                groups[gid] = { goalId:t.goal_id||'', goalTitle:t.goal_title||'未关联项目', goalStatus:t.goal_status||'', tasks:[] };
                order.push(gid);
            }
            groups[gid].tasks.push(t);
        });

        // 按目标组状态过滤
        const filteredOrder = currentGoalFilter === 'all' ? order : order.filter(gid => {
            return groups[gid].goalStatus === currentGoalFilter;
        });

        if (filteredOrder.length === 0) {
            el('taskModalBody').innerHTML = '<div class="task-empty">当前目标组筛选条件下暂无任务</div>';
            return;
        }

        // 点击目标组按钮时收缩，点击任务按钮时展开
        const shouldCollapse = shouldCollapseGoals;

        let html = '';
        filteredOrder.forEach(gid => {
            const g = groups[gid];
            const cnt = g.tasks.length;
            const avg = g.tasks.reduce((s,t) => s + (t.progress||0), 0) / cnt;
            const sc = {};
            g.tasks.forEach(t => { sc[t.status] = (sc[t.status]||0)+1; });
            const summary = Object.entries(sc).map(([k,v]) => { const n = {pending:'待认领',running:'运行中',completed:'已完成',failed:'失败',blocked:'阻塞',interrupted:'中断',review:'审查中'}; return (n[k]||k)+' '+v; }).join(' · ');
            const reviewCount = sc['review'] || 0;
            const progressColor = avg >= 100 ? 'var(--green)' : avg >= 50 ? 'var(--yellow)' : 'var(--accent)';

            html += '<div class="goal-group">';
            html += '<div class="goal-group-header" onclick="toggleGoalGroup(this)">';
            html += '<div class="goal-group-left">';
            html += '<span class="goal-group-arrow'+(shouldCollapse?' collapsed':'')+'">'+(shouldCollapse?'\u25b6':'\u25bc')+'</span>';
            html += '<span class="goal-group-icon">🎯</span>';
            html += '<span class="goal-group-title">'+esc(g.goalTitle)+'</span>';
            html += getGoalStatusBadge(g.goalStatus);
            // 目标状态切换按钮
            html += '<span class="goal-status-actions" onclick="event.stopPropagation()">';
            var goalStatuses = [{key:'active',label:'▶ 进行中',cls:'st-active'},{key:'pending',label:'⏸ 暂停',cls:'st-pending'},{key:'completed',label:'✓ 完成',cls:'st-completed'},{key:'cancelled',label:'✕ 取消',cls:'st-cancelled'}];
            goalStatuses.forEach(function(gs){
                var isCurrent = g.goalStatus === gs.key;
                html += '<button class="btn-goal-status '+gs.cls+(isCurrent?' st-current':'')+'" ';
                if (!isCurrent) html += 'onclick="updateGoalStatusFromTask(\''+esc(g.goalId)+'\',\''+gs.key+'\')"\ ';
                html += 'title="'+(isCurrent?'当前状态':'切换到'+gs.label)+'">'+gs.label+'</button>';
            });
            html += '</span>';
            // 全部审查按钮：仅当目标组内所有任务都已完成时显示
            var allCompleted = g.tasks.length > 0 && g.tasks.every(function(t){ return t.status === 'completed'; });
            if (allCompleted) {
                html += '<button class="btn-review-all" onclick="event.stopPropagation();reviewAllTasks(\''+esc(g.goalId)+'\',\''+esc(g.goalTitle)+'\')"\ title="将所有任务切换为审查状态">🔍 全部审查</button>';
            }
            // review批量操作按钮：当有review状态任务时显示
            if (reviewCount > 0) {
                html += '<span class="review-batch-actions" onclick="event.stopPropagation()" style="display:inline-flex;align-items:center;gap:4px;margin-left:4px;">';
                html += '<button class="btn-review-pass" onclick="reviewBatchPass(\''+esc(g.goalId)+'\',\''+esc(g.goalTitle)+'\')" title="批量通过所有review任务" style="background:var(--green);color:#fff;border:none;border-radius:4px;padding:2px 8px;font-size:11px;cursor:pointer;font-weight:600;">✅ 全部通过 ('+reviewCount+')</button>';
                html += '<button class="btn-review-fail" onclick="reviewBatchFail(\''+esc(g.goalId)+'\',\''+esc(g.goalTitle)+'\')" title="批量拒绝所有review任务" style="background:var(--red);color:#fff;border:none;border-radius:4px;padding:2px 8px;font-size:11px;cursor:pointer;font-weight:600;">❌ 全部拒绝 ('+reviewCount+')</button>';
                html += '</span>';
            }
            html += '<span class="goal-group-count">'+cnt+' 个任务</span>';
            html += '<button class="btn-delete-group" onclick="event.stopPropagation();deleteTasksByGoal(\''+esc(g.goalId)+'\',\''+esc(g.goalTitle)+'\')"\ title="删除全部">🗑</button>';
            html += '</div><div class="goal-group-right">';
            html += '<span class="goal-group-summary">'+summary+'</span>';
            html += '<div class="goal-progress-mini"><div class="goal-progress-mini-fill" style="width:'+avg.toFixed(0)+'%;background:'+progressColor+';"></div></div>';
            html += '<span style="font-size:10px;color:var(--text-muted);">'+avg.toFixed(0)+'%</span>';
            html += '</div></div>';

            // ===== 树状/瀑布结构渲染 =====
            html += '<div class="goal-group-body" style="padding:8px 12px;'+(shouldCollapse?'display:none;':'')+'">';

            // 构建依赖图 → 拓扑排序 → 层级渲染
            const taskMap = {};
            g.tasks.forEach(t => { taskMap[t.id] = t; });
            const depOf = {};  // taskId → 被哪些任务依赖
            const depOn = {};  // taskId → 依赖哪些任务
            g.tasks.forEach(t => {
                depOn[t.id] = (t.dependencies || []).filter(d => taskMap[d]);
                depOn[t.id].forEach(d => {
                    if (!depOf[d]) depOf[d] = [];
                    depOf[d].push(t.id);
                });
            });

            // 拓扑排序获取层级
            const levels = {};
            const inDegree = {};
            g.tasks.forEach(t => { inDegree[t.id] = (depOn[t.id] || []).length; });
            let queue = g.tasks.filter(t => inDegree[t.id] === 0).map(t => t.id);
            let level = 0;
            const ordered = [];
            while (queue.length > 0) {
                const next = [];
                queue.forEach(id => {
                    levels[id] = level;
                    ordered.push(id);
                    (depOf[id] || []).forEach(child => {
                        inDegree[child]--;
                        if (inDegree[child] === 0) next.push(child);
                    });
                });
                queue = next;
                level++;
            }
            // 未被拓扑排序到的（循环依赖），放在最后
            g.tasks.forEach(t => { if (!ordered.includes(t.id)) { levels[t.id] = level; ordered.push(t.id); } });

            // 树状表头
            html += '<div style="display:flex;align-items:center;padding:6px 8px;border-bottom:2px solid var(--border-light);font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">';
            html += '<div style="width:36px;flex-shrink:0;">层</div>';
            html += '<div style="width:110px;flex-shrink:0;">ID</div>';
            html += '<div style="flex:1;min-width:0;">任务</div>';
            html += '<div style="width:95px;flex-shrink:0;">状态</div>';
            html += '<div style="width:110px;flex-shrink:0;">进度</div>';
            html += '<div style="width:80px;flex-shrink:0;">依赖</div>';
            html += '<div style="width:80px;flex-shrink:0;">类型</div>';
            html += '<div style="width:80px;flex-shrink:0;">执行者</div>';
            html += '<div style="width:50px;flex-shrink:0;text-align:center;">优先</div>';
            html += '<div style="width:50px;flex-shrink:0;text-align:center;">难度</div>';
            html += '<div style="width:70px;flex-shrink:0;text-align:center;">操作</div>';
            html += '</div>';

            ordered.forEach((tid, idx) => {
                const t = taskMap[tid];
                if (!t) return;
                const lvl = levels[tid] || 0;
                const p = t.progress || 0;
                const deps = depOn[tid] || [];
                const children = depOf[tid] || [];
                const isLast = idx === ordered.length - 1 || (levels[ordered[idx+1]] || 0) <= lvl;
                const desc = t.description ? t.description.substring(0,40)+(t.description.length>40?'…':'') : '';

                html += '<div class="tree-task-row">';

                // 树状缩进 + 连接线
                html += '<div style="width:'+(36 + lvl*24)+'px;flex-shrink:0;display:flex;align-items:center;justify-content:flex-end;padding-right:6px;">';
                if (lvl === 0) {
                    html += '<span style="width:8px;height:8px;border-radius:50%;background:var(--green);flex-shrink:0;" title="根任务"></span>';
                } else {
                    // 竖线 + 横线 + 圆点
                    html += '<span style="display:inline-flex;align-items:center;">';
                    for (let l = 0; l < lvl - 1; l++) {
                        html += '<span style="width:24px;border-left:2px solid var(--border);height:28px;display:inline-block;"></span>';
                    }
                    html += '<span style="display:inline-flex;align-items:center;">';
                    html += '<span style="width:24px;height:28px;border-left:2px solid var(--border);border-bottom:2px solid var(--border);border-radius:0 0 0 6px;display:inline-block;vertical-align:middle;margin-bottom:14px;"></span>';
                    html += '<span style="width:6px;height:6px;border-radius:50%;background:var(--purple);flex-shrink:0;" title="子任务 (层级 '+lvl+')"></span>';
                    html += '</span></span>';
                }
                html += '</div>';

                // 内容行
                html += '<div style="flex:1;min-width:0;display:flex;align-items:center;gap:4px;font-size:12px;padding:4px 0;">';

                // ID
                html += '<div style="width:110px;flex-shrink:0;"><span style="color:var(--accent);font-size:10px;font-family:monospace;cursor:pointer;" title="点击复制" onclick="copyId(this,\''+esc(t.id)+'\')">'+esc(t.id)+'</span></div>';

                // 任务名 + 依赖标签
                html += '<div style="flex:1;min-width:0;">';
                html += '<div class="task-title" style="font-size:12px;">'+esc(t.title||t.id);
                // 父子任务标记
                if (t.parent_task_id) {
                    var parentTask = taskMap[t.parent_task_id];
                    var parentName = parentTask ? parentTask.title : t.parent_task_id.substring(0,12)+'…';
                    html += ' <span style="font-size:9px;background:var(--purple);color:#fff;padding:1px 5px;border-radius:3px;margin-left:4px;" title="父任务: '+esc(parentName)+'">🔀 子任务</span>';
                }
                // review结果标记
                if (t.review_result === 'passed') {
                    var reviewTime = t.reviewed_at ? ' · '+(t.reviewed_at||'').substring(0,10) : '';
                    var reviewTip = (t.reviewed_by ? '审查人: '+t.reviewed_by : '') + (t.review_comment ? '\n意见: '+t.review_comment : '') + reviewTime;
                    html += ' <span style="font-size:9px;background:var(--green);color:#fff;padding:1px 6px;border-radius:3px;margin-left:4px;" title="'+esc(reviewTip)+'">✅ 通过'+reviewTime+'</span>';
                } else if (t.review_result === 'failed') {
                    var reviewTime2 = t.reviewed_at ? ' · '+(t.reviewed_at||'').substring(0,10) : '';
                    var reviewTip2 = (t.reviewed_by ? '审查人: '+t.reviewed_by : '') + (t.review_comment ? '\n意见: '+t.review_comment : '') + reviewTime2;
                    html += ' <span style="font-size:9px;background:var(--red);color:#fff;padding:1px 6px;border-radius:3px;margin-left:4px;" title="'+esc(reviewTip2)+'">❌ 拒绝'+reviewTime2+'</span>';
                }
                if (deps.length > 0) {
                    deps.forEach(did => {
                        const dt = taskMap[did];
                        const depName = dt ? dt.title : did.substring(0,10)+'…';
                        const depStatus = dt ? dt.status : 'unknown';
                        const depDone = depStatus === 'completed';
                    html += ' <span class="tree-dep-label" title="依赖: '+esc(depName)+' ('+depStatus+')" style="'+(depDone?'opacity:0.5;text-decoration:line-through;':'')+'">← '+esc(depName.substring(0,12))+(depDone?' ✓':' ⏳')+' <span class="dep-remove-btn" title="移除此依赖" onclick="event.stopPropagation();removeDependency(\''+esc(t.id)+'\',\''+esc(did)+'\')">&times;</span></span>';
                    });
                }
                html += '</div>';
                if (desc) html += '<div class="task-desc" title="'+esc(t.description)+'">'+esc(desc)+'</div>';
                html += '</div>';

                // 状态（可修改下拉）
                html += '<div style="width:95px;flex-shrink:0;">'+getStatusSelect(t.id, t.status)+'</div>';

                // 进度
                html += '<div style="width:110px;flex-shrink:0;display:flex;align-items:center;gap:4px;">';
                html += '<div class="task-progress-bar"><div class="task-progress-fill '+getProgressColor(p)+'" style="width:'+p+'%"></div></div>';
                html += '<span style="font-size:10px;color:var(--text-muted);">'+p.toFixed(0)+'%</span></div>';

                // 依赖数
                html += '<div style="width:80px;flex-shrink:0;">';
                if (deps.length > 0 || children.length > 0) {
                    html += '<span style="font-size:10px;color:var(--purple);">';
                    if (deps.length > 0) html += '↑'+deps.length;
                    if (deps.length > 0 && children.length > 0) html += ' ';
                    if (children.length > 0) html += '<span style="color:var(--green);">↓'+children.length+'</span>';
                    html += '</span>';
                } else {
                    html += '<span style="font-size:10px;color:var(--text-dimmed);">—</span>';
                }
                html += '</div>';

                // 类型
                html += '<div style="width:80px;flex-shrink:0;font-size:11px;color:var(--text-muted);">'+esc(t.skill_type||'—')+'</div>';

                // 执行者
                html += '<div style="width:80px;flex-shrink:0;font-size:11px;color:var(--text-muted);">'+esc(t.claimed_by||'—')+'</div>';

                // 优先级
                html += '<div style="width:50px;flex-shrink:0;text-align:center;"><span style="color:var(--yellow);font-size:11px;font-weight:700;">'+(t.priority||0)+'</span></div>';

                // 难度标签
                var diff = t.difficulty || 5;
                var diffColor = diff <= 3 ? 'var(--green)' : diff <= 6 ? 'var(--yellow)' : diff <= 9 ? 'var(--orange,#f0883e)' : 'var(--red)';
                var diffLabel = diff <= 3 ? '简单' : diff <= 6 ? '中等' : diff <= 9 ? '困难' : '极难';
                html += '<div style="width:50px;flex-shrink:0;text-align:center;"><span style="color:'+diffColor+';font-size:10px;font-weight:700;" title="难度: '+diff+'/10">'+diffLabel+'</span></div>';

                // 操作
                html += '<div style="width:70px;flex-shrink:0;text-align:center;"><span class="btn-action-group">';
                html += '<button class="btn-edit" title="编辑" onclick="event.stopPropagation();openTaskEdit(\''+esc(t.id)+'\')">✏️</button>';
                html += '<button class="btn-delete" title="删除" onclick="event.stopPropagation();deleteTask(\''+esc(t.id)+'\',\''+esc(t.title||t.id)+'\')">🗑</button>';
                if (t.status === 'running') html += '<button class="btn-edit" title="拆分为子任务" onclick="event.stopPropagation();openSplitTask(\''+esc(t.id)+'\',\''+esc(t.title||t.id)+'\')" style="font-size:10px;">✂️</button>';
                html += '</span></div>';

                html += '</div></div>'; // 关闭内容行 + tree-task-row
            });

            html += '</div></div>'; // 关闭 goal-group-body + goal-group
        });
        el('taskModalBody').innerHTML = html;
    }

    function toggleGoalGroup(headerEl) {
        const body = headerEl.parentElement.querySelector('.goal-group-body');
        const arrow = headerEl.querySelector('.goal-group-arrow');
        if (body.style.display === 'none') {
            body.style.display = 'block';
            arrow.classList.remove('collapsed');
            arrow.textContent = '▼';
        } else {
            body.style.display = 'none';
            arrow.classList.add('collapsed');
            arrow.textContent = '▶';
        }
    }

    function copyId(elem, id) {
        navigator.clipboard.writeText(id);
        elem.style.color = 'var(--green)';
        setTimeout(() => elem.style.color = 'var(--accent)', 1000);
        showToast('已复制: ' + id, 'success');
    }

    // ===== Delete Operations =====
    function deleteTask(taskId, taskTitle) {
        if (!confirm('确定删除任务「'+taskTitle+'」？')) return;
        fetch('/api/tasks/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({task_id:taskId})})
            .then(r => r.json())
            .then(data => {
                if (data.error) { showToast('删除失败: '+data.error, 'error'); }
                else { showToast('已删除任务', 'success'); fetchTasks(); loadDashboardData(); }
            })
            .catch(err => showToast('删除失败: '+err.message, 'error'));
    }

    function deleteTasksByGoal(goalId, goalTitle) {
        if (!confirm('确定删除「'+goalTitle+'」下所有任务？\n此操作不可恢复！')) return;
        fetch('/api/tasks/delete-by-goal', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({goal_id:goalId})})
            .then(r => r.json())
            .then(data => {
                if (data.error) { showToast('删除失败: '+data.error, 'error'); }
                else { showToast('已删除 '+data.deleted_count+' 个任务', 'success'); fetchTasks(); loadDashboardData(); }
            })
            .catch(err => showToast('删除失败: '+err.message, 'error'));
    }

    // ===== Task Split (任务拆分) =====
    function openSplitTask(taskId, taskTitle) {
        var subtasksJSON = prompt(
            '拆分任务「'+taskTitle+'」为子任务\n\n' +
            '请输入子任务列表（JSON数组格式）:\n' +
            '[\n  {"title":"子任务1","description":"描述1"},\n  {"title":"子任务2","description":"描述2","dependencies":["子任务1"]}\n]\n\n' +
            '提示：dependencies 支持标题引用，skill_type/phase 不填则继承父任务',
            '[{"title":"","description":""}]'
        );
        if (!subtasksJSON) return;
        try {
            var subtasks = JSON.parse(subtasksJSON);
            if (!Array.isArray(subtasks) || subtasks.length === 0) {
                showToast('子任务列表不能为空', 'error'); return;
            }
            // 验证每个子任务有 title 和 description
            for (var i = 0; i < subtasks.length; i++) {
                if (!subtasks[i].title || !subtasks[i].description) {
                    showToast('第'+(i+1)+'个子任务缺少 title 或 description', 'error'); return;
                }
            }
        } catch(e) {
            showToast('JSON格式错误: '+e.message, 'error'); return;
        }

        fetch('/api/tasks/split', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({parent_task_id: taskId, subtasks: subtasks})
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) { showToast('拆分失败: '+data.error, 'error'); }
            else { showToast('已拆分为 '+data.subtask_count+' 个子任务', 'success'); fetchTasks(); loadDashboardData(); }
        })
        .catch(err => showToast('拆分失败: '+err.message, 'error'));
    }

    // ===== Task Edit =====
    function openTaskEdit(taskId) {
        const task = allTasks.find(t => t.id === taskId);
        if (!task) { showToast('未找到任务信息', 'error'); return; }
        el('taskEditTaskId').value = task.id;
        el('taskEditId').textContent = task.id;
        el('taskEditTitle').value = task.title || '';
        el('taskEditDesc').value = task.description || '';
        el('taskEditPriority').value = task.priority || 5;
        el('taskEditDifficulty').value = task.difficulty || 5;
        el('taskEditSkillType').value = task.skill_type || '';
        el('taskEditPhase').value = task.phase || '';
        el('taskEditTokens').value = task.estimated_tokens || '';
        // 设置依赖标签选择器
        currentEditDeps = (task.dependencies || []).slice();
        currentEditGoalTasks = getGoalTasksForTask(task.id);
        renderEditDepTags();
        populateDepSelect();
        // 显示review信息（如有）
        var reviewBlock = el('taskEditReviewBlock');
        var reviewInfo = el('taskEditReviewInfo');
        if (task.review_result) {
            var resultLabel = task.review_result === 'passed'
                ? '<span style="color:var(--green);font-weight:700;">✅ 通过</span>'
                : '<span style="color:var(--red);font-weight:700;">❌ 拒绝</span>';
            var infoHtml = '结果：' + resultLabel;
            if (task.reviewed_at) infoHtml += '　时间：' + task.reviewed_at.substring(0, 19).replace('T', ' ');
            if (task.reviewed_by) infoHtml += '　审查人：' + esc(task.reviewed_by);
            if (task.review_comment) infoHtml += '<br>意见：' + esc(task.review_comment);
            reviewInfo.innerHTML = infoHtml;
            reviewBlock.style.display = '';
        } else {
            reviewBlock.style.display = 'none';
        }
        el('taskEditOverlay').classList.add('active');
    }

    function closeTaskEdit() {
        el('taskEditOverlay').classList.remove('active');
    }
    el('taskEditOverlay').addEventListener('click', function(e) { if (e.target === this) closeTaskEdit(); });

    function submitTaskEdit() {
        const taskId = el('taskEditTaskId').value;
        if (!taskId) return;
        const fields = {};
        const title = el('taskEditTitle').value.trim();
        const desc = el('taskEditDesc').value.trim();
        const priority = parseInt(el('taskEditPriority').value);
        const difficulty = parseInt(el('taskEditDifficulty').value);
        const skillType = el('taskEditSkillType').value;
        const phase = el('taskEditPhase').value.trim();
        const tokens = parseInt(el('taskEditTokens').value);

        if (title) fields.title = title;
        if (desc) fields.description = desc;
        if (!isNaN(priority) && priority >= 1 && priority <= 10) fields.priority = priority;
        if (!isNaN(difficulty) && difficulty >= 1 && difficulty <= 10) fields.difficulty = difficulty;
        if (skillType) fields.skill_type = skillType;
        if (phase) fields.phase = phase;
        if (!isNaN(tokens) && tokens > 0) fields.estimated_tokens = tokens;
        fields.dependencies = currentEditDeps.slice();

        if (Object.keys(fields).length === 0) {
            showToast('请至少修改一个字段', 'info');
            return;
        }

        el('taskEditSubmit').disabled = true;
        el('taskEditSubmit').textContent = '保存中...';
        fetch('/api/tasks/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ task_id: taskId, fields: fields })
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                showToast('修改失败: ' + data.error, 'error');
            } else {
                showToast('任务已更新', 'success');
                closeTaskEdit();
                fetchTasks();
                loadDashboardData();
            }
        })
        .catch(err => showToast('修改失败: ' + err.message, 'error'))
        .finally(() => {
            el('taskEditSubmit').disabled = false;
            el('taskEditSubmit').textContent = '保存修改';
        });
    }

    // ===== Dependency Management =====
    var currentEditDeps = [];       // 当前编辑中的依赖列表
    var currentEditGoalTasks = [];  // 同目标下的可选任务

    function getGoalTasksForTask(taskId) {
        // 从 allTasks 找出与 taskId 同一个 goal 的所有任务
        const task = allTasks.find(t => t.id === taskId);
        if (!task || !task.goal_id) return allTasks.filter(t => t.id !== taskId);
        return allTasks.filter(t => t.goal_id === task.goal_id && t.id !== taskId);
    }

    function renderEditDepTags() {
        const container = el('taskEditDepTags');
        if (currentEditDeps.length === 0) {
            container.innerHTML = '<span class="dep-tag-empty">无依赖 — 从下方选择添加</span>';
            return;
        }
        let html = '';
        currentEditDeps.forEach(depId => {
            const t = allTasks.find(tt => tt.id === depId);
            const name = t ? (t.title || depId) : depId;
            html += '<span class="dep-tag">';
            html += '<span title="'+esc(depId)+'">'+esc(name.substring(0,20))+'</span>';
            html += '<span class="dep-tag-remove" onclick="removeEditDep(\''+esc(depId)+'\')"> &times;</span>';
            html += '</span>';
        });
        container.innerHTML = html;
    }

    function populateDepSelect() {
        const select = el('taskEditDepSelect');
        const taskId = el('taskEditTaskId').value;
        let html = '<option value="">— 选择要添加的依赖任务 —</option>';
        currentEditGoalTasks.forEach(t => {
            if (t.id === taskId) return;
            if (currentEditDeps.includes(t.id)) return; // 已在依赖列表中
            const label = (t.title || t.id) + ' (' + (t.status || 'unknown') + ')';
            html += '<option value="'+esc(t.id)+'">'+esc(label)+'</option>';
        });
        select.innerHTML = html;
    }

    function addDepFromSelect() {
        const select = el('taskEditDepSelect');
        const val = select.value;
        if (!val) { showToast('请先选择一个任务', 'info'); return; }
        if (!currentEditDeps.includes(val)) {
            currentEditDeps.push(val);
        }
        renderEditDepTags();
        populateDepSelect();
    }

    function removeEditDep(depId) {
        currentEditDeps = currentEditDeps.filter(d => d !== depId);
        renderEditDepTags();
        populateDepSelect();
    }

    function clearAllDeps() {
        currentEditDeps = [];
        renderEditDepTags();
        populateDepSelect();
    }

    // 任务行上直接移除单个依赖
    function removeDependency(taskId, depId) {
        const task = allTasks.find(t => t.id === taskId);
        if (!task) { showToast('未找到任务', 'error'); return; }
        const newDeps = (task.dependencies || []).filter(d => d !== depId);
        const depTask = allTasks.find(t => t.id === depId);
        const depName = depTask ? (depTask.title || depId) : depId;
        if (!confirm('确定要移除对「' + depName + '」的依赖吗？')) return;
        fetch('/api/tasks/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ task_id: taskId, fields: { dependencies: newDeps } })
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                showToast('移除依赖失败: ' + data.error, 'error');
            } else {
                showToast('已移除依赖「' + depName + '」', 'success');
                fetchTasks();
                loadDashboardData();
            }
        })
        .catch(err => showToast('移除依赖失败: ' + err.message, 'error'));
    }

    // ===== Helpers =====
    function el(id) { return document.getElementById(id); }
    function esc(s) { if (!s) return ''; return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

    // ===== Recovery Timeline Functions =====
    async function loadRecoveryData() {
        const taskFilter = document.getElementById('recoveryTaskFilter')?.value?.trim() || '';
        const agentFilter = document.getElementById('recoveryAgentFilter')?.value?.trim() || '';
        
        let url = '/api/recovery-timeline?';
        if (taskFilter) url += `task_id=${encodeURIComponent(taskFilter)}&`;
        if (agentFilter) url += `agent_id=${encodeURIComponent(agentFilter)}&`;
        
        try {
            const resp = await fetch(url);
            const data = await resp.json();
            renderRecoveryStats(data.stats || {});
            renderRecoveryTimelines(data.timelines || []);
        } catch (e) {
            console.error('加载恢复链路数据失败:', e);
            document.getElementById('recoveryTimelines').innerHTML = 
                '<div class="card" style="text-align:center;padding:40px;color:var(--red);">❌ 加载失败: ' + e.message + '</div>';
        }
    }

    function renderRecoveryStats(stats) {
        const counts = stats.event_counts || {};
        document.getElementById('recovery-interrupted-count').textContent = counts.interrupted || 0;
        document.getElementById('recovery-recovered-count').textContent = stats.recovered_task_count || 0;
        document.getElementById('recovery-completed-count').textContent = stats.completed_after_recovery || 0;
        
        const avgSec = stats.avg_recovery_seconds || 0;
        let avgText = '-';
        if (avgSec > 0) {
            if (avgSec < 60) avgText = Math.round(avgSec) + 's';
            else if (avgSec < 3600) avgText = Math.round(avgSec / 60) + 'min';
            else avgText = (avgSec / 3600).toFixed(1) + 'h';
        }
        document.getElementById('recovery-avg-time').textContent = avgText;
    }

    function renderRecoveryTimelines(timelines) {
        const container = document.getElementById('recoveryTimelines');
        
        if (!timelines || timelines.length === 0) {
            container.innerHTML = `
                <div class="recovery-empty">
                    <div class="icon">🎉</div>
                    <div style="font-size:16px;font-weight:600;margin-bottom:8px;">暂无恢复链路数据</div>
                    <div style="font-size:12px;color:var(--text-dimmed);">当任务发生中断→恢复→完成的链路时，数据将自动记录在此</div>
                </div>`;
            return;
        }
        
        // 按最新事件时间排序
        timelines.sort((a, b) => {
            const aTime = a.events?.length ? a.events[0].created_at : '';
            const bTime = b.events?.length ? b.events[0].created_at : '';
            return bTime.localeCompare(aTime);
        });
        
        let html = '';
        for (const tl of timelines) {
            const events = (tl.events || []).slice().reverse(); // 时间正序显示
            const statusBadge = getStatusBadge(tl.status);
            const progressPct = parseFloat(tl.progress || 0).toFixed(1);
            
            html += `<div class="timeline-card">`;
            html += `<div class="timeline-header">`;
            html += `<div class="timeline-task-title" title="${escapeHtml(tl.task_id)}">`;
            html += `${escapeHtml(tl.title || tl.task_id)}</div>`;
            html += `<div class="timeline-task-meta">`;
            html += `${statusBadge}`;
            html += `<span class="badge" style="font-size:10px;">${progressPct}%</span>`;
            if (tl.skill_type) html += `<span class="badge" style="font-size:10px;">${tl.skill_type}</span>`;
            if (tl.claimed_by) html += `<span style="font-size:10px;color:var(--text-dimmed);">👤 ${tl.claimed_by}</span>`;
            if (tl.has_checkpoint) html += `<span style="font-size:10px;color:var(--green);">💾 有检查点</span>`;
            html += `</div></div>`;
            
            // 时间线事件列表
            html += `<div class="timeline-events">`;
            for (const ev of events) {
                const icon = getEventIcon(ev.event_type);
                const timeStr = formatEventTime(ev.created_at);
                
                html += `<div class="timeline-event">`;
                html += `<div class="timeline-dot ${ev.event_type}"></div>`;
                html += `<div class="timeline-event-header">`;
                html += `<span class="timeline-event-type ${ev.event_type}">${icon} ${ev.event_type}</span>`;
                html += `<span class="timeline-event-time">${timeStr}</span>`;
                if (ev.progress > 0) {
                    html += `<span class="timeline-event-progress">📊 ${parseFloat(ev.progress).toFixed(1)}%</span>`;
                }
                html += `</div>`;
                html += `<div class="timeline-event-detail">${escapeHtml(ev.detail || '')}</div>`;
                html += `</div>`;
            }
            html += `</div>`;
            html += `</div>`;
        }
        
        container.innerHTML = html;
    }

    function getEventIcon(eventType) {
        const icons = {
            'interrupted': '🔴',
            'resumed': '🟢',
            'completed': '✅',
            'failed': '❌',
            'soft_timeout': '⚠️',
            'blocked': '🟣'
        };
        return icons[eventType] || '⚪';
    }

    function getStatusBadge(status) {
        const styles = {
            'completed': 'background:var(--green-bg);color:var(--green);',
            'running': 'background:var(--blue-bg);color:var(--blue);',
            'failed': 'background:var(--red-bg);color:var(--red);',
            'interrupted': 'background:var(--yellow-bg);color:var(--yellow);',
            'pending': 'background:var(--bg-tertiary);color:var(--text-muted);',
            'blocked': 'background:var(--purple-bg);color:var(--purple);'
        };
        const style = styles[status] || styles['pending'];
        return `<span class="badge" style="font-size:10px;${style}">${status || 'unknown'}</span>`;
    }

    function formatEventTime(isoStr) {
        if (!isoStr) return '';
        try {
            const d = new Date(isoStr.replace(' ', 'T') + 'Z');
            if (isNaN(d.getTime())) return isoStr;
            const now = new Date();
            const diffMs = now - d;
            const diffMin = Math.floor(diffMs / 60000);
            if (diffMin < 1) return '刚刚';
            if (diffMin < 60) return diffMin + ' 分钟前';
            const diffH = Math.floor(diffMin / 60);
            if (diffH < 24) return diffH + ' 小时前';
            const diffD = Math.floor(diffH / 24);
            if (diffD < 7) return diffD + ' 天前';
            return d.toLocaleDateString('zh-CN', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
        } catch(e) { return isoStr; }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ===== Fix Experience Functions =====
    function loadFixExpData() {
        loadFixExpStats();
        loadFixExperiences();
    }

    function loadFixExpStats() {
        fetch('/api/fix-experiences/stats')
            .then(r => r.json())
            .then(data => {
                if (data.error) return;
                el('fixexp-total-exp').textContent = data.total_experiences || 0;
                el('fixexp-positive-exp').textContent = data.positive_experiences || 0;
                el('fixexp-negative-exp').textContent = data.negative_experiences || 0;
            })
            .catch(() => {});
    }

    // ===== 经验编辑/删除操作 =====
    function deleteFixExperience(id, type) {
        if (!confirm('确定要删除这条' + (type === 'positive' ? '正面' : '负面') + '经验吗？\n\nID: ' + id + '\n\n此操作不可撤销！')) return;
        fetch('/api/fix-experiences/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({type: type, id: id})
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) { showToast('删除失败: ' + data.error, 'error'); return; }
            showToast('经验已删除', 'success');
            loadFixExperiences();
        })
        .catch(err => showToast('删除失败: ' + err.message, 'error'));
    }

    function editFixExperience(id, type, btnEl) {
        const expData = JSON.parse(btnEl.getAttribute('data-exp'));
        document.getElementById('expEditId').value = id;
        document.getElementById('expEditType').value = type;
        document.getElementById('expEditDesc').value = expData.description || '';
        document.getElementById('expEditSolution').value = expData.solution || '';
        document.getElementById('expEditRootCause').value = expData.root_cause || '';
        document.getElementById('expEditSkillType').value = expData.skill_type || '';
        document.getElementById('expEditCategory').value = expData.category || '';
        document.getElementById('expEditSeverity').value = expData.severity || '';
        document.getElementById('expEditConfidence').value = expData.confidence || '';
        document.getElementById('expEditTitle').textContent = '✏️ 编辑经验';
        document.getElementById('expEditSaveBtn').textContent = '💾 保存';
        document.getElementById('expEditTypeRow').style.display = 'none';
        document.getElementById('expEditOverlay').classList.add('active');
    }

    function closeExpEditModal() {
        document.getElementById('expEditOverlay').classList.remove('active');
    }

    function saveFixExperience() {
        const id = document.getElementById('expEditId').value;
        const type = document.getElementById('expEditType').value;
        const isCreate = !id;
        const fields = {};
        const desc = document.getElementById('expEditDesc').value.trim();
        const solution = document.getElementById('expEditSolution').value.trim();
        const rootCause = document.getElementById('expEditRootCause').value.trim();
        const skillType = document.getElementById('expEditSkillType').value.trim();
        const category = document.getElementById('expEditCategory').value.trim();
        const severity = document.getElementById('expEditSeverity').value;
        const confidence = document.getElementById('expEditConfidence').value.trim();
        if (desc) fields.description = desc;
        if (solution) fields.solution = solution;
        if (rootCause) fields.root_cause = rootCause;
        if (skillType) fields.skill_type = skillType;
        if (category) fields.category = category;
        if (severity) fields.severity = severity;
        if (confidence) fields.confidence = confidence;
        if (Object.keys(fields).length === 0) { showToast('请至少填写一个字段', 'error'); return; }

        if (isCreate) {
            // 新建模式
            const createType = document.getElementById('expEditTypeSelect').value;
            if (!fields.description) { showToast('描述不能为空', 'error'); return; }
            fetch('/api/fix-experiences/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({type: createType, fields: fields})
            })
            .then(r => r.json())
            .then(data => {
                if (data.error) { showToast('创建失败: ' + data.error, 'error'); return; }
                showToast('经验已创建 (ID: ' + (data.id || '').substring(0, 15) + ')', 'success');
                closeExpEditModal();
                // 切换到对应类型并刷新
                document.getElementById('fixExpTypeFilter').value = createType;
                loadFixExperiences();
            })
            .catch(err => showToast('创建失败: ' + err.message, 'error'));
        } else {
            // 编辑模式
            fetch('/api/fix-experiences/update', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({type: type, id: id, fields: fields})
            })
            .then(r => r.json())
            .then(data => {
                if (data.error) { showToast('更新失败: ' + data.error, 'error'); return; }
                showToast('经验已更新', 'success');
                closeExpEditModal();
                loadFixExperiences();
            })
            .catch(err => showToast('更新失败: ' + err.message, 'error'));
        }
    }

    // ===== 新建经验 =====
    function openCreateExperience() {
        // 清空表单
        document.getElementById('expEditId').value = '';
        document.getElementById('expEditType').value = '';
        document.getElementById('expEditDesc').value = '';
        document.getElementById('expEditSolution').value = '';
        document.getElementById('expEditRootCause').value = '';
        document.getElementById('expEditSkillType').value = '';
        document.getElementById('expEditCategory').value = '';
        document.getElementById('expEditSeverity').value = '';
        document.getElementById('expEditConfidence').value = '0.8';
        // 设置新建模式 UI
        document.getElementById('expEditTitle').textContent = '➕ 新建经验';
        document.getElementById('expEditSaveBtn').textContent = '✨ 创建';
        document.getElementById('expEditTypeRow').style.display = 'block';
        document.getElementById('expEditTypeSelect').value = document.getElementById('fixExpTypeFilter').value;
        document.getElementById('expEditOverlay').classList.add('active');
    }

    // ===== 吸收远程经验 =====
    // ===== 整理经验（去重+自动标注 pattern_tags）=====
    function organizeExperiences() {
        if (!confirm('确认执行经验整理？\n\n这将执行以下操作：\n1. 去重：删除完全相同描述的重复经验\n2. 自动标注：为缺少 pattern_tags 的经验自动推断抽象模式标签\n\n标注后的经验将支持跨组件/跨文件的语义召回。')) {
            return;
        }
        showToast('⏳ 正在整理经验库...', 'info', 15000);

        fetch('/api/fix-experiences/organize', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                showToast('❌ 整理失败: ' + data.error, 'error');
                return;
            }
            var processed = data.total_processed || 0;
            var dupRemoved = data.duplicates_removed || 0;
            var tagsAdded = data.tags_added || 0;
            var details = data.details || [];

            var msg = '🧹 经验整理完成！\n';
            msg += '• 处理经验: ' + processed + ' 条\n';
            msg += '• 删除重复: ' + dupRemoved + ' 条\n';
            msg += '• 标注标签: ' + tagsAdded + ' 条';
            if (details.length > 0) {
                msg += '\n\n标注示例:\n';
                var showCount = Math.min(details.length, 3);
                for (var i = 0; i < showCount; i++) {
                    var d = details[i];
                    msg += '• ' + (d.tags || []).join(', ') + ' → ' + (d.desc || '').substring(0, 40) + '...\n';
                }
            }

            showToast(msg, dupRemoved > 0 || tagsAdded > 0 ? 'success' : 'info', 8000);
            // 刷新经验列表
            loadFixExperiences();
        })
        .catch(function(err) {
            showToast('❌ 网络错误: ' + err.message, 'error');
        });
    }

    function openAbsorbExperience() {
        document.getElementById('absorbAddr').value = '';
        document.getElementById('absorbTypePositive').checked = true;
        document.getElementById('absorbTypeNegative').checked = true;
        document.getElementById('absorbKeyword').value = '';
        document.getElementById('absorbResult').style.display = 'none';
        document.getElementById('absorbResult').innerHTML = '';
        document.getElementById('absorbSubmitBtn').disabled = false;
        document.getElementById('absorbSubmitBtn').textContent = '🔗 开始吸收';
        document.getElementById('absorbExpOverlay').classList.add('active');
    }

    function closeAbsorbModal() {
        document.getElementById('absorbExpOverlay').classList.remove('active');
    }

    function submitAbsorbExperience() {
        var addr = document.getElementById('absorbAddr').value.trim();
        if (!addr) { showToast('请输入远程 MCP Dashboard 地址', 'error'); return; }

        var types = [];
        if (document.getElementById('absorbTypePositive').checked) types.push('positive');
        if (document.getElementById('absorbTypeNegative').checked) types.push('negative');
        if (types.length === 0) { showToast('请至少选择一种经验类型', 'error'); return; }

        var keyword = document.getElementById('absorbKeyword').value.trim();

        var btn = document.getElementById('absorbSubmitBtn');
        btn.disabled = true;
        btn.textContent = '⏳ 吸收中...';

        var resultDiv = document.getElementById('absorbResult');
        resultDiv.style.display = 'block';
        resultDiv.innerHTML = '<div style="text-align:center;color:var(--accent);padding:12px;"><span style="animation:spin 1s linear infinite;display:inline-block;">⏳</span> 正在连接远程实例并拉取经验数据...</div>';

        fetch('/api/fix-experiences/absorb', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({remote_addr: addr, types: types, keyword: keyword})
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            btn.disabled = false;
            btn.textContent = '🔗 再次吸收';
            if (data.error) {
                resultDiv.innerHTML = '<div style="padding:12px;border-radius:var(--radius-xs);background:rgba(248,81,73,0.1);border-left:3px solid var(--red);"><span style="color:var(--red);font-weight:600;">❌ 吸收失败</span><div style="font-size:12px;color:var(--text-muted);margin-top:4px;">' + esc(data.error) + '</div></div>';
                return;
            }
            var html = '<div style="padding:12px;border-radius:var(--radius-xs);background:rgba(63,185,80,0.1);border-left:3px solid var(--green);">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
            html += '<span style="color:var(--green);font-weight:700;font-size:14px;">✅ 吸收完成</span>';
            html += '<span style="font-size:11px;color:var(--text-muted);">来源: ' + esc(data.remote_addr || addr) + '</span>';
            html += '</div>';
            html += '<div style="display:flex;gap:16px;font-size:13px;margin-bottom:8px;">';
            html += '<span style="color:var(--green);font-weight:600;">📥 吸收: ' + (data.total_absorbed || 0) + ' 条</span>';
            html += '<span style="color:var(--accent);">🔀 去重: ' + (data.total_duplicate || 0) + ' 条</span>';
            html += '<span style="color:var(--yellow);">⏭ 跳过: ' + (data.total_skipped || 0) + ' 条</span>';
            html += '<span style="color:var(--red);">❌ 失败: ' + (data.total_failed || 0) + ' 条</span>';
            html += '</div>';
            // 详情
            if (data.details) {
                html += '<div style="font-size:11px;color:var(--text-muted);border-top:1px solid var(--border);padding-top:6px;margin-top:4px;">';
                for (var t in data.details) {
                    var d = data.details[t];
                    var icon = t === 'positive' ? '✅' : '❌';
                    if (d.error) {
                        html += '<div>' + icon + ' ' + t + ': <span style="color:var(--red);">' + esc(d.error) + '</span></div>';
                    } else {
                        html += '<div>' + icon + ' ' + t + ': 拉取 ' + (d.fetched||0) + ' → 吸收 ' + (d.absorbed||0) + ' / 去重 ' + (d.duplicate||0) + ' / 跳过 ' + (d.skipped||0) + ' / 失败 ' + (d.failed||0) + '</div>';
                    }
                }
                html += '</div>';
            }
            html += '</div>';
            resultDiv.innerHTML = html;

            // 刷新本地经验列表和统计
            loadFixExpStats();
            loadFixExperiences();
        })
        .catch(function(err) {
            btn.disabled = false;
            btn.textContent = '🔗 重试吸收';
            resultDiv.innerHTML = '<div style="padding:12px;border-radius:var(--radius-xs);background:rgba(248,81,73,0.1);border-left:3px solid var(--red);"><span style="color:var(--red);font-weight:600;">❌ 网络错误</span><div style="font-size:12px;color:var(--text-muted);margin-top:4px;">' + esc(err.message) + '</div></div>';
        });
    }

    function loadFixExperiences() {
        const expType = document.getElementById('fixExpTypeFilter').value;
        const keyword = document.getElementById('fixExpKeyword').value.trim();
        const params = 'type=' + expType + '&limit=50' + (keyword ? '&keyword=' + encodeURIComponent(keyword) : '');
        fetch('/api/fix-experiences?' + params)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    el('fixExperiencesList').innerHTML = '<div style="color:var(--red);padding:12px;">' + esc(data.error) + '</div>';
                    return;
                }
                const exps = data.experiences || [];
                if (exps.length === 0) {
                    el('fixExperiencesList').innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:24px;">暂无' + (keyword ? '匹配' : '') + '经验</div>';
                    return;
                }
                let html = '';
                exps.forEach(exp => {
                    const isPositive = expType === 'positive';
                    const borderColor = isPositive ? 'var(--green)' : 'var(--red)';
                    const icon = isPositive ? '✅' : '❌';
                    const confText = exp.confidence ? (parseFloat(exp.confidence) * 100).toFixed(0) + '%' : '-';
                    const expJSON = esc(JSON.stringify(exp));
                    html += '<div style="background:var(--bg-tertiary);border-left:3px solid ' + borderColor + ';border-radius:var(--radius-xs);padding:12px;">' +
                        '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">' +
                        '<div style="display:flex;gap:6px;align-items:center;">' +
                        '<span>' + icon + '</span>' +
                        '<span class="badge badge-blue">' + esc(exp.skill_type || '-') + '</span>' +
                        '<span class="badge badge-gray">' + esc(exp.category || '-') + '</span>' +
                        (exp.severity ? '<span class="badge" style="background:' + ({critical:'var(--red)',high:'var(--orange)',medium:'var(--yellow)',low:'var(--green)'}[exp.severity] || 'var(--text-dimmed)') + ';color:#fff;font-size:9px;">' + esc(exp.severity) + '</span>' : '') +
                        (exp.source === 'manual' ? '<span class="badge" style="background:var(--purple);color:#fff;font-size:9px;">手动</span>' : '') +
                        '</div>' +
                        '<div style="display:flex;gap:6px;align-items:center;">' +
                        '<span style="font-size:10px;color:var(--text-dimmed);">可信度: ' + confText + '</span>' +
                        '<button onclick=\'editFixExperience("' + esc(exp.id) + '","' + expType + '",this)\' data-exp="' + expJSON + '" style="background:none;border:1px solid var(--border);color:var(--accent);cursor:pointer;font-size:11px;padding:2px 8px;border-radius:4px;transition:all 0.15s;" onmouseover="this.style.background=\'var(--accent-bg)\'" onmouseout="this.style.background=\'none\'">✏️ 编辑</button>' +
                        '<button onclick=\'deleteFixExperience("' + esc(exp.id) + '","' + expType + '")\' style="background:none;border:1px solid var(--border);color:var(--red);cursor:pointer;font-size:11px;padding:2px 8px;border-radius:4px;transition:all 0.15s;" onmouseover="this.style.background=\'rgba(248,81,73,0.1)\'" onmouseout="this.style.background=\'none\'">🗑️ 删除</button>' +
                        '</div>' +
                        '</div>' +
                        '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:4px;">' + esc(exp.description || '') + '</div>' +
                        (exp.solution ? '<div style="font-size:12px;color:var(--green);"><strong>解决方案:</strong> ' + esc(exp.solution) + '</div>' : '') +
                        (exp.root_cause ? '<div style="font-size:12px;color:var(--yellow);margin-top:2px;"><strong>根因:</strong> ' + esc(exp.root_cause) + '</div>' : '') +
                        '<div style="font-size:10px;color:var(--text-dimmed);margin-top:6px;">ID: ' + esc(exp.id || '').substring(0, 20) + ' | Task: ' + esc(exp.task_id || '-').substring(0, 16) + '</div>' +
                        '</div>';
                });
                el('fixExperiencesList').innerHTML = html;
            })
            .catch(err => {
                el('fixExperiencesList').innerHTML = '<div style="color:var(--red);padding:12px;">加载失败: ' + esc(err.message) + '</div>';
            });
    }
    // ===== Complaints Functions =====
    let complaintsCursor = '';
    let complaintsHasMore = false;

    function loadComplaintsData() {
        loadComplaintStats();
        loadComplaintsList(true);
    }

    function loadComplaintStats() {
        fetch('/api/complaints/stats')
            .then(r => r.json())
            .then(data => {
                el('complaint-total').textContent = data.total_count || 0;
                const bySev = data.by_severity || {};
                el('complaint-blocking').textContent = bySev.blocking || 0;
                el('complaint-frustrating').textContent = bySev.frustrating || 0;
                el('complaint-minor').textContent = bySev.minor || 0;

                // 计算严重占比提示
                const total = data.total_count || 0;
                if (total > 0) {
                    const blockPct = ((bySev.blocking || 0) / total * 100).toFixed(0);
                    const frusPct = ((bySev.frustrating || 0) / total * 100).toFixed(0);
                    el('complaint-total-sub').textContent = 'blocking ' + blockPct + '% / frustrating ' + frusPct + '%';
                } else {
                    el('complaint-total-sub').textContent = '暂无吐槽记录';
                }

                // 按类型分布
                renderComplaintTypeChart(data.by_type || {});
                // 热点
                renderComplaintHotSpots(data.hot_spots || []);
            })
            .catch(err => {
                el('complaint-total-sub').textContent = '加载失败';
            });
    }

    function renderComplaintTypeChart(byType) {
        const typeLabels = {experience:'🧠 经验', tool:'🔧 工具', skill:'📐 Skill', workflow:'🔄 流程', context:'📝 上下文', performance:'⚡ 性能', other:'❓ 其他'};
        const entries = Object.entries(byType).sort((a,b) => b[1] - a[1]);
        if (entries.length === 0) {
            el('complaintByType').innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:24px;">暂无数据</div>';
            return;
        }
        const maxVal = Math.max(...entries.map(e => e[1]));
        let html = '<div style="display:flex;flex-direction:column;gap:8px;">';
        entries.forEach(([type, count]) => {
            const pct = maxVal > 0 ? (count / maxVal * 100) : 0;
            const label = typeLabels[type] || type;
            html += '<div style="display:flex;align-items:center;gap:10px;">' +
                '<div style="width:90px;font-size:12px;color:var(--text-secondary);text-align:right;flex-shrink:0;">' + label + '</div>' +
                '<div style="flex:1;background:var(--bg-tertiary);border-radius:4px;height:22px;overflow:hidden;">' +
                '<div style="width:' + pct + '%;height:100%;background:var(--accent);border-radius:4px;transition:width 0.5s;display:flex;align-items:center;justify-content:flex-end;padding-right:6px;">' +
                '<span style="font-size:10px;color:#fff;font-weight:600;">' + count + '</span></div></div></div>';
        });
        html += '</div>';
        el('complaintByType').innerHTML = html;
    }

    function renderComplaintHotSpots(hotSpots) {
        if (!hotSpots || hotSpots.length === 0) {
            el('complaintHotSpots').innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:24px;">🎉 暂无高频热点（count≥3 的 frustrating/blocking 级吐槽）</div>';
            return;
        }
        const sevColors = {blocking:'var(--red)', frustrating:'var(--yellow)', minor:'var(--text-muted)'};
        const dimLabels = {type:'类型', tool:'工具', skill:'Skill', skil:'Skill'};
        let html = '<div style="display:flex;flex-direction:column;gap:8px;">';
        hotSpots.slice(0, 5).forEach((hs, i) => {
            const color = sevColors[hs.severity] || 'var(--text-muted)';
            const dim = dimLabels[hs.dimension] || hs.dimension;
            html += '<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--bg-tertiary);border-radius:var(--radius-xs);border-left:3px solid ' + color + ';">' +
                '<div style="font-size:18px;font-weight:800;color:' + color + ';width:28px;text-align:center;">' + (i+1) + '</div>' +
                '<div style="flex:1;">' +
                '<div style="font-size:13px;color:var(--text-primary);font-weight:600;">' + esc(hs.value) + '</div>' +
                '<div style="font-size:11px;color:var(--text-muted);">' + dim + ' · ' + hs.count + ' 次吐槽 · 最高严重度: <span style="color:' + color + ';">' + hs.severity + '</span></div>' +
                '</div></div>';
        });
        html += '</div>';
        el('complaintHotSpots').innerHTML = html;
    }

    function loadComplaintsList(reset) {
        if (reset) {
            complaintsCursor = '';
            el('complaintsList').innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:24px;">加载中...</div>';
        }
        const filterType = el('complaintTypeFilter').value;
        let url = '/api/complaints?limit=20';
        if (filterType) url += '&type=' + encodeURIComponent(filterType);
        if (complaintsCursor) url += '&cursor=' + encodeURIComponent(complaintsCursor);

        fetch(url)
            .then(r => r.json())
            .then(data => {
                const complaints = data.complaints || [];
                complaintsCursor = data.cursor || '';
                complaintsHasMore = data.has_more || false;

                if (reset && complaints.length === 0) {
                    el('complaintsList').innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:40px;"><div style="font-size:32px;margin-bottom:8px;">😌</div>暂无吐槽记录</div>';
                    el('complaintsLoadMore').style.display = 'none';
                    return;
                }

                const sevBadge = {blocking:'background:var(--red);color:#fff;', frustrating:'background:var(--yellow);color:#000;', minor:'background:var(--bg-tertiary);color:var(--text-muted);'};
                const typeIcons = {experience:'🧠', tool:'🔧', skill:'📐', workflow:'🔄', context:'📝', performance:'⚡', other:'❓'};

                let html = '';
                complaints.forEach(c => {
                    const sevStyle = sevBadge[c.severity] || sevBadge.minor;
                    const icon = typeIcons[c.type] || '❓';
                    const time = c.created_at ? new Date(c.created_at).toLocaleString('zh-CN') : '-';
                    html += '<div style="padding:12px 14px;background:var(--bg-tertiary);border-radius:var(--radius-xs);border-left:3px solid ' + (c.severity==='blocking'?'var(--red)':c.severity==='frustrating'?'var(--yellow)':'var(--border)') + ';">' +
                        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">' +
                        '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">' +
                        '<span class="badge" style="' + sevStyle + 'font-size:10px;padding:2px 8px;border-radius:10px;font-weight:600;">' + esc(c.severity || '') + '</span>' +
                        '<span class="badge badge-blue" style="font-size:10px;">' + icon + ' ' + esc(c.type || '') + '</span>' +
                        (c.related_tool ? '<span class="badge badge-gray" style="font-size:10px;">🔧 ' + esc(c.related_tool) + '</span>' : '') +
                        (c.related_skill ? '<span class="badge badge-gray" style="font-size:10px;">📐 ' + esc(c.related_skill) + '</span>' : '') +
                        '</div>' +
                        '<span style="font-size:10px;color:var(--text-dimmed);flex-shrink:0;">' + time + '</span>' +
                        '</div>' +
                        '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:4px;line-height:1.5;">' + esc(c.complaint || '') + '</div>' +
                        (c.suggestion ? '<div style="font-size:12px;color:var(--green);margin-top:4px;"><strong>💡 建议:</strong> ' + esc(c.suggestion) + '</div>' : '') +
                        '<div style="font-size:10px;color:var(--text-dimmed);margin-top:6px;">' +
                        (c.agent_id ? 'Agent: ' + esc(c.agent_id) : '') +
                        (c.related_task_id ? ' | Task: ' + esc(c.related_task_id).substring(0, 16) : '') +
                        ' | ID: ' + esc(c.id || '').substring(0, 20) +
                        '</div></div>';
                });

                if (reset) {
                    el('complaintsList').innerHTML = html;
                } else {
                    el('complaintsList').innerHTML += html;
                }
                el('complaintsLoadMore').style.display = complaintsHasMore ? 'block' : 'none';
            })
            .catch(err => {
                if (reset) {
                    el('complaintsList').innerHTML = '<div style="color:var(--red);padding:12px;">加载失败: ' + esc(err.message) + '</div>';
                }
            });
    }

    function loadMoreComplaints() {
        loadComplaintsList(false);
    }

    // ==================== Project Lifecycle ====================

    let currentProjectID = null;
    let currentPhaseName = null;

    // 加载流程列表
    async function loadProjects() {
        // 确保显示列表面板，隐藏详情面板
        document.getElementById('projectsListPanel').style.display = 'block';
        document.getElementById('projectDetailPanel').style.display = 'none';
        currentProjectID = null;
        currentPhaseName = null;
        
        const status = document.getElementById('projectStatusFilter')?.value || '';
        const url = `/api/projects${status ? '?status=' + status : ''}`;
        
        try {
            const resp = await fetch(url);
            const data = await resp.json();
            renderProjectsList(data.projects || []);
        } catch(e) {
            document.getElementById('projectsList').innerHTML = `<div class="empty-state">加载失败: ${e.message}</div>`;
        }
    }

    // 渲染流程列表
    function renderProjectsList(projects) {
        const container = document.getElementById('projectsList');
        if (!projects || projects.length === 0) {
            container.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:40px;">暂无流程，点击"新建流程"开始</div>';
            return;
        }
        
        const phaseOrder = ['idea', 'macro_supplement', 'research', 'mvp', 'p1', 'p2'];
        const phaseLabels = {
            'idea': '创意', 'macro_supplement': '宏观', 'research': '调研',
            'mvp': 'MVP', 'p1': 'P1', 'p2': 'P2'
        };
        const statusColors = {
            'draft': '#6b7280', 'idea_review': '#8b5cf6', 'macro_supplement': '#3b82f6',
            'research': '#06b6d4', 'mvp': '#f59e0b', 'p1': '#10b981', 'p2': '#22c55e',
            'completed': '#16a34a', 'cancelled': '#ef4444'
        };
        const statusLabels = {
            'draft': '草稿', 'idea_review': '创意审阅', 'macro_supplement': '宏观补充',
            'research': '调研', 'mvp': 'MVP', 'p1': 'P1', 'p2': 'P2',
            'completed': '已完成', 'cancelled': '已取消'
        };
        
        container.innerHTML = projects.map(p => {
            const currentPhaseIdx = phaseOrder.indexOf(p.current_phase);
            const phasesHtml = phaseOrder.map((phase, idx) => {
                let cls = 'phase-dot';
                if (idx < currentPhaseIdx) cls += ' phase-done';
                else if (idx === currentPhaseIdx) cls += ' phase-active';
                return `<div class="${cls}" title="${phaseLabels[phase]}">${phaseLabels[phase]}</div>`;
            }).join('<div class="phase-line"></div>');
            
            const statusColor = statusColors[p.status] || '#6b7280';
            const tags = (p.tags || []).map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('');
            
            return `
            <div class="project-card" onclick="openProjectDetail('${p.id}')">
                <div class="project-card-header">
                    <div>
                        <div class="project-title">${escapeHtml(p.title)}</div>
                        <div class="project-desc">${escapeHtml((p.description || '').substring(0, 100))}${(p.description || '').length > 100 ? '...' : ''}</div>
                    </div>
                    <div style="text-align:right;flex-shrink:0;">
                        <span class="status-badge" style="background:${statusColor}20;color:${statusColor};border:1px solid ${statusColor}40;">${statusLabels[p.status] || p.status}</span>
                        <div style="margin-top:4px;font-size:12px;color:var(--text-muted);">优先级 ${p.priority}</div>
                    </div>
                </div>
                <div class="phase-timeline" style="margin-top:12px;">
                    ${phasesHtml}
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;">
                    <div>${tags}</div>
                    <button class="project-delete-btn" onclick="event.stopPropagation();showDeleteProjectDialog('${p.id}','${escapeHtml(p.title)}')" title="删除流程">🗑️ 删除</button>
                </div>
            </div>`;
        }).join('');
    }

    // 删除流程确认弹窗
    function showDeleteProjectDialog(projectID, projectTitle) {
        const dialog = document.createElement('div');
        dialog.className = 'modal-overlay';
        dialog.style.display = 'flex';
        dialog.innerHTML = `
        <div class="modal" style="max-width:420px;">
            <div class="modal-header">
                <h3>⚠️ 删除流程</h3>
                <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</button>
            </div>
            <div class="modal-body" style="padding:20px;">
                <div style="background:#ef444420;border:1px solid #ef444440;border-radius:8px;padding:12px;margin-bottom:16px;">
                    <div style="font-size:14px;font-weight:600;color:#ef4444;">⚠️ 此操作不可撤销！</div>
                    <div style="font-size:13px;color:var(--text-muted);margin-top:4px;">将永久删除流程 <strong style="color:var(--text-primary);">${escapeHtml(projectTitle)}</strong> 及其所有阶段数据。</div>
                </div>
                <div style="margin-bottom:12px;">
                    <label style="font-size:13px;color:var(--text-muted);display:block;margin-bottom:6px;">请输入流程名称以确认删除：</label>
                    <input type="text" id="deleteProjectConfirmInput" placeholder="${escapeHtml(projectTitle)}" 
                           style="width:100%;padding:8px 12px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);font-size:14px;box-sizing:border-box;" />
                </div>
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;">
                    <input type="checkbox" id="deleteProjectCascade" />
                    <label for="deleteProjectCascade" style="font-size:13px;color:var(--text-muted);">同时删除关联的 Goal 和 Task</label>
                </div>
                <div style="display:flex;gap:8px;justify-content:flex-end;">
                    <button class="btn btn-secondary" onclick="this.closest('.modal-overlay').remove()">取消</button>
                    <button class="btn" id="deleteProjectBtn" style="background:#ef4444;color:#fff;" onclick="confirmDeleteProject('${projectID}','${escapeHtml(projectTitle)}',this)">删除流程</button>
                </div>
            </div>
        </div>`;
        document.body.appendChild(dialog);
        
        // 输入框实时验证
        const input = dialog.querySelector('#deleteProjectConfirmInput');
        const btn = dialog.querySelector('#deleteProjectBtn');
        btn.disabled = true;
        btn.style.opacity = '0.5';
        btn.style.cursor = 'not-allowed';
        input.addEventListener('input', () => {
            const match = input.value.trim() === projectTitle;
            btn.disabled = !match;
            btn.style.opacity = match ? '1' : '0.5';
            btn.style.cursor = match ? 'pointer' : 'not-allowed';
        });
        input.focus();
    }
    
    async function confirmDeleteProject(projectID, projectTitle, btn) {
        const input = document.getElementById('deleteProjectConfirmInput');
        const cascade = document.getElementById('deleteProjectCascade').checked;
        
        if (input.value.trim() !== projectTitle) {
            alert('流程名称不匹配');
            return;
        }
        
        btn.disabled = true;
        btn.textContent = '删除中...';
        
        try {
            const resp = await fetch(`/api/projects/${projectID}`, {
                method: 'DELETE',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({confirm_name: projectTitle, cascade: cascade})
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || '删除失败');
            
            // 关闭弹窗并刷新列表
            btn.closest('.modal-overlay').remove();
            showToast('✅ 流程已删除', 'success');
            loadProjects();
        } catch(e) {
            btn.disabled = false;
            btn.textContent = '删除流程';
            alert('删除失败: ' + e.message);
        }
    }

    // 打开流程详情
    async function openProjectDetail(projectID) {
        currentProjectID = projectID;
        // 隐藏流程列表，显示流程详情面板
        document.getElementById('projectsListPanel').style.display = 'none';
        document.getElementById('projectDetailPanel').style.display = 'block';
        document.getElementById('projectDetailBody').innerHTML = '<div class="skeleton" style="height:300px;border-radius:8px;"></div>';
        
        try {
            const resp = await fetch(`/api/projects/${projectID}`);
            const data = await resp.json();
            renderProjectDetail(data);
        } catch(e) {
            document.getElementById('projectDetailBody').innerHTML = `<div style="text-align:center;color:var(--text-muted);padding:40px;">加载失败: ${e.message}</div>`;
        }
    }

    // 渲染流程详情
    function renderProjectDetail(data) {
        const project = data.project || data;
        const phases = data.phases || [];
        const history = data.history || [];
        
        document.getElementById('projectDetailTitle').textContent = project.title;
        
        const techStack = (project.tech_stack || []).join(', ') || '未设置';
        const riskList = (project.risk_list || []).map(r => `<li>${escapeHtml(r)}</li>`).join('') || '<li>暂无风险记录</li>';
        
        const phaseLabels = {
            'idea': '创意', 'macro_supplement': '宏观', 'research': '调研',
            'mvp': 'MVP', 'p1': 'P1', 'p2': 'P2'
        };
        const phaseStatusIcons = {
            'pending': '⏳', 'active': '🔄', 'completed': '✅', 'skipped': '⏭️'
        };
        const phaseStatusLabels = {
            'pending': '待定', 'active': '进行中', 'completed': '已完成', 'skipped': '已跳过'
        };
        const gateStatusColors = {
            'pending': '#6b7280', 'approved': '#10b981', 'rejected': '#ef4444',
            'revision_requested': '#f59e0b', 'in_review': '#3b82f6'
        };
        const gateStatusLabels = {
            'pending': '待审批', 'approved': '已通过', 'rejected': '已驳回',
            'revision_requested': '需修订', 'in_review': '审阅中'
        };
        
        // 脑图树状结构 - 递归渲染函数（支持子阶段）
        function renderPhaseBranches(phaseList, depth) {
            return phaseList.map((phase, idx) => {
                const icon = phaseStatusIcons[phase.status] || '⏳';
                const gateColor = gateStatusColors[phase.gate_status] || '#6b7280';
                const isActive = phase.status === 'active';
                const isCompleted = phase.status === 'completed';
                const phaseLabel = phaseLabels[phase.name] || phase.name;
                const gateLabel = gateStatusLabels[phase.gate_status] || gateStatusLabels['pending'];
                const goalCount = phase.linked_goals || 0;
                const children = phase.children || [];
                const hasChildren = children.length > 0;
                
                // 递归渲染子阶段
                const childBranchesHtml = hasChildren ? `
                    <div class="mindmap-sub-branches" id="mindmap-sub-${phase.name}">
                        ${renderPhaseBranches(children, depth + 1)}
                        <div class="mindmap-branch mindmap-add-branch">
                            <div class="mindmap-add-phase mindmap-add-sub" onclick="showAddPhaseDialog('${project.id}', '${phase.name}')">
                                <span>➕</span><span>添加子阶段</span>
                            </div>
                        </div>
                    </div>` : '';
                
                return `
                <div class="mindmap-branch ${depth > 0 ? 'mindmap-branch-sub depth-' + depth : ''}">
                    <div style="display:flex;align-items:center;gap:6px;">
                        <div class="mindmap-phase ${isActive ? 'active' : ''} ${isCompleted ? 'completed' : ''}" data-phase="${phase.name}" 
                             onclick="toggleMindmapPhase(this, '${project.id}', '${phase.name}')">
                            <span class="mindmap-phase-icon">${icon}</span>
                            <span>${phaseLabel}</span>
                            <span class="mindmap-phase-gate" style="background:${gateColor}20;color:${gateColor};">${gateLabel}</span>
                            <span class="mindmap-phase-count">${goalCount} 目标</span>
                            <span class="mindmap-toggle">${goalCount > 0 ? '▶' : ''}</span>
                        </div>
                        <div class="mindmap-phase-actions">
                            <button class="mindmap-action-btn" title="添加子阶段" onclick="event.stopPropagation();showAddPhaseDialog('${project.id}','${phase.name}')">
                                ➕
                            </button>
                            <button class="mindmap-action-btn" title="编辑阶段" onclick="event.stopPropagation();showEditPhaseDialog('${project.id}','${phase.name}','${escapeHtml(phase.description || '')}')">
                                ✏️
                            </button>
                            <button class="mindmap-action-btn mindmap-action-del" title="删除阶段" onclick="event.stopPropagation();removePhase('${project.id}','${phase.name}')">
                                🗑️
                            </button>
                        </div>
                    </div>
                    <div class="mindmap-children" id="mindmap-children-${phase.name}">
                        <div style="padding:8px 0;color:var(--text-muted);font-size:12px;">加载中...</div>
                    </div>
                    ${childBranchesHtml}
                </div>`;
            }).join('');
        }
        
        const branchesHtml = renderPhaseBranches(phases, 0);
        
        document.getElementById('projectDetailBody').innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px;">
            <div>
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                    <span style="font-size:13px;color:var(--text-muted);font-weight:600;">描述</span>
                    <button onclick="toggleEditField('projDesc','${project.id}','description')" style="background:none;border:none;cursor:pointer;font-size:12px;color:var(--accent);padding:0;" title="编辑描述">✏️</button>
                </div>
                <div id="projDescDisplay" style="font-size:14px;">${escapeHtml(project.description || '暂无描述')}</div>
                <div id="projDescEdit" style="display:none;">
                    <textarea id="projDescInput" style="width:100%;min-height:60px;padding:6px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);font-size:13px;resize:vertical;">${escapeHtml(project.description || '')}</textarea>
                    <div style="display:flex;gap:6px;margin-top:6px;">
                        <button class="btn btn-primary" style="padding:4px 12px;font-size:12px;" onclick="saveProjectField('${project.id}','description','projDescInput')">保存</button>
                        <button class="btn" style="padding:4px 12px;font-size:12px;" onclick="cancelEditField('projDesc')">取消</button>
                    </div>
                </div>
            </div>
            <div>
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                    <span style="font-size:13px;color:var(--text-muted);font-weight:600;">愿景</span>
                    <button onclick="toggleEditField('projVision','${project.id}','vision')" style="background:none;border:none;cursor:pointer;font-size:12px;color:var(--accent);padding:0;" title="编辑愿景">✏️</button>
                </div>
                <div id="projVisionDisplay" style="font-size:14px;">${escapeHtml(project.vision || '暂无愿景')}</div>
                <div id="projVisionEdit" style="display:none;">
                    <textarea id="projVisionInput" style="width:100%;min-height:60px;padding:6px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);font-size:13px;resize:vertical;">${escapeHtml(project.vision || '')}</textarea>
                    <div style="display:flex;gap:6px;margin-top:6px;">
                        <button class="btn btn-primary" style="padding:4px 12px;font-size:12px;" onclick="saveProjectField('${project.id}','vision','projVisionInput')">保存</button>
                        <button class="btn" style="padding:4px 12px;font-size:12px;" onclick="cancelEditField('projVision')">取消</button>
                    </div>
                </div>
            </div>
            <div>
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                    <span style="font-size:13px;color:var(--text-muted);font-weight:600;">技术栈</span>
                    <button onclick="toggleEditField('projTechStack','${project.id}','tech_stack')" style="background:none;border:none;cursor:pointer;font-size:12px;color:var(--accent);padding:0;" title="编辑技术栈">✏️</button>
                </div>
                <div id="projTechStackDisplay" style="font-size:14px;">${escapeHtml(techStack)}</div>
                <div id="projTechStackEdit" style="display:none;">
                    <input type="text" id="projTechStackInput" placeholder="逗号分隔，如: Go, React, Redis" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);font-size:13px;" value="${escapeHtml((project.tech_stack || []).join(', '))}">
                    <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">多个技术栈用英文逗号分隔</div>
                    <div style="display:flex;gap:6px;margin-top:6px;">
                        <button class="btn btn-primary" style="padding:4px 12px;font-size:12px;" onclick="saveProjectField('${project.id}','tech_stack','projTechStackInput')">保存</button>
                        <button class="btn" style="padding:4px 12px;font-size:12px;" onclick="cancelEditField('projTechStack')">取消</button>
                    </div>
                </div>
            </div>
            <div>
                <div style="font-size:13px;color:var(--text-muted);margin-bottom:4px;">当前阶段</div>
                <div style="font-size:14px;font-weight:600;">${phaseLabels[project.current_phase] || project.current_phase || '未开始'}</div>
            </div>
        </div>
        
        <div style="margin-bottom:20px;">
            <div style="font-size:13px;color:var(--text-muted);margin-bottom:8px;">⚠️ 风险清单</div>
            <ul style="margin:0;padding-left:20px;font-size:13px;">${riskList}</ul>
        </div>
        
        <div style="margin-bottom:20px;">
            <div style="font-size:14px;font-weight:600;margin-bottom:12px;">🧠 阶段总览</div>
            <div class="mindmap">
                <div class="mindmap-root">
                    <div class="mindmap-root-node">📋 ${escapeHtml(project.title)}</div>
                    <div class="mindmap-hline"></div>
            <div class="mindmap-branches">
                        ${branchesHtml}
                        <div class="mindmap-branch mindmap-add-branch">
                            <div class="mindmap-add-phase" onclick="showAddPhaseDialog('${project.id}', '')">
                                <span>➕</span>
                                <span>添加阶段</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div style="font-size:12px;color:var(--text-muted);margin-top:8px;">💡 点击阶段节点展开查看目标与任务详情</div>
        </div>
        
        <div id="phasePanel" style="display:none;border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:20px;">
            <div id="phasePanelContent">加载中...</div>
        </div>
        
        <div>
            <div style="font-size:14px;font-weight:600;margin-bottom:12px;">📜 审批历史</div>
            ${history.length === 0 ? '<div style="text-align:center;color:var(--text-muted);padding:12px;">暂无审批历史</div>' :
                history.map(h => {
                    const actionLabels = {'approved': '通过', 'rejected': '驳回', 'submitted': '提交', 'revision_requested': '请求修订'};
                    const actionLabel = actionLabels[h.action] || h.action;
                    const phaseLabel = phaseLabels[h.phase_name] || h.phase_name;
                    return `
                <div style="display:flex;gap:12px;padding:8px 0;border-bottom:1px solid var(--border);">
                    <div style="font-size:20px;">${h.action === 'approved' ? '✅' : h.action === 'rejected' ? '❌' : h.action === 'submitted' ? '📤' : '📝'}</div>
                    <div>
                        <div style="font-size:13px;font-weight:500;">${actionLabel} - ${phaseLabel}</div>
                        <div style="font-size:12px;color:var(--text-muted);">${h.actor} · ${h.created_at ? new Date(h.created_at).toLocaleString('zh-CN') : ''}</div>
                        ${h.comment ? `<div style="font-size:12px;margin-top:4px;">${escapeHtml(h.comment)}</div>` : ''}
                    </div>
                </div>`; }).join('')
            }
        </div>`;
    }

    // ===== 脑图树状交互 =====
    // 切换脑图阶段展开/折叠
    async function toggleMindmapPhase(el, projectID, phaseName) {
        const childrenContainer = document.getElementById('mindmap-children-' + phaseName);
        const toggle = el.querySelector('.mindmap-toggle');
        
        if (childrenContainer.classList.contains('expanded')) {
            // 折叠
            childrenContainer.classList.remove('expanded');
            if (toggle) toggle.classList.remove('open');
        } else {
            // 展开并加载数据
            childrenContainer.classList.add('expanded');
            if (toggle) toggle.classList.add('open');
            childrenContainer.innerHTML = '<div style="padding:6px 0;color:var(--text-muted);font-size:12px;">加载中...</div>';
            
            try {
                const resp = await fetch(`/api/projects/${projectID}/phases/${phaseName}/overview`);
                const overview = await resp.json();
                renderMindmapChildren(projectID, phaseName, overview, childrenContainer);
            } catch(e) {
                childrenContainer.innerHTML = `<div style="padding:6px 0;color:#ef4444;font-size:12px;">加载失败: ${e.message}</div>`;
            }
        }
        
        // 同时加载下方的 Phase 详情面板
        currentPhaseName = phaseName;
        const panel = document.getElementById('phasePanel');
        panel.style.display = 'block';
        
        const phaseLabelsLocal = {
            'idea': '创意', 'macro_supplement': '宏观', 'research': '调研',
            'mvp': 'MVP', 'p1': 'P1', 'p2': 'P2'
        };
        document.getElementById('phasePanelContent').innerHTML = `<div style="font-size:14px;font-weight:600;margin-bottom:12px;">📌 ${phaseLabelsLocal[phaseName] || phaseName} 阶段详情</div><div class="skeleton" style="height:150px;border-radius:8px;"></div>`;
        
        try {
            const resp = await fetch(`/api/projects/${projectID}/phases/${phaseName}/overview`);
            const overview = await resp.json();
            renderPhasePanel(projectID, phaseName, overview);
        } catch(e) {
            document.getElementById('phasePanelContent').innerHTML = `<div style="text-align:center;color:var(--text-muted);padding:40px;">加载失败: ${e.message}</div>`;
        }
    }
    
    // 渲染脑图二级/三级子节点（目标 → 任务）
    function renderMindmapChildren(projectID, phaseName, overview, container) {
        const goals = overview.goals || [];
        const goalStatusColors = {'active': '#3b82f6', 'completed': '#10b981', 'pending': '#6b7280', 'cancelled': '#ef4444'};
        const goalStatusLabels = {'active': '进行中', 'completed': '已完成', 'pending': '待定', 'cancelled': '已取消'};
        const taskStatusColors = {'pending': '#6b7280', 'running': '#3b82f6', 'completed': '#10b981', 'failed': '#ef4444', 'blocked': '#f59e0b', 'interrupted': '#f97316', 'review': '#8b5cf6'};
        const taskStatusLabels = {'pending': '待认领', 'running': '运行中', 'completed': '已完成', 'failed': '失败', 'blocked': '阻塞', 'interrupted': '中断', 'review': '审查中'};
        
        if (goals.length === 0) {
            container.innerHTML = `<div class="mindmap-child"><div style="font-size:12px;color:var(--text-muted);padding:4px 0;">暂无关联目标</div></div>
            <div class="mindmap-child mindmap-add-child">
                <div class="mindmap-add-goal" onclick="showLinkGoalDialog('${projectID}','${phaseName}')"><span>➕</span> 关联目标</div>
                <div class="mindmap-add-goal" onclick="showLinkTaskDialog('${projectID}','${phaseName}')" style="margin-left:8px;"><span>➕</span> 关联任务</div>
            </div>`;
            return;
        }
        
        const goalsHtml = goals.map((goal, gIdx) => {
            const goalColor = goalStatusColors[goal.status] || '#6b7280';
            const goalLabel = goalStatusLabels[goal.status] || goal.status;
            const tasks = goal.tasks || [];
            const hasTask = tasks.length > 0;
            
            const tasksHtml = tasks.map(task => {
                const taskColor = taskStatusColors[task.status] || '#6b7280';
                const taskLabel = taskStatusLabels[task.status] || task.status;
                return `
                <div class="mindmap-task">
                    <div class="mindmap-task-node" onclick="openTaskDetailById('${task.task_id}')">
                        <span class="mindmap-task-status" style="background:${taskColor}20;color:${taskColor};">●</span>
                        <span>${escapeHtml(task.title || task.task_id)}</span>
                        <span class="mindmap-task-status" style="background:${taskColor}15;color:${taskColor};">${taskLabel}</span>
                        ${task.claimed_by ? `<span style="font-size:10px;color:var(--text-muted);">@${task.claimed_by}</span>` : ''}
                    </div>
                </div>`;
            }).join('');
            
            return `
            <div class="mindmap-child">
                <div class="mindmap-goal" onclick="toggleMindmapGoalTasks(this, '${phaseName}-goal-${gIdx}')">
                    <span>🎯</span>
                    <span>${escapeHtml(goal.title || goal.goal_id)}</span>
                    <span class="mindmap-goal-status" style="background:${goalColor}20;color:${goalColor};">${goalLabel}</span>
                    <span style="font-size:10px;color:var(--text-muted);">${goal.completed_tasks || 0}/${goal.total_tasks || 0}</span>
                    ${hasTask ? '<span class="mindmap-toggle">▶</span>' : ''}
                </div>
                <div class="mindmap-tasks" id="mindmap-tasks-${phaseName}-goal-${gIdx}">
                    ${tasksHtml || '<div class="mindmap-task"><div style="font-size:11px;color:var(--text-muted);padding:2px 0;">暂无任务</div></div>'}
                </div>
            </div>`;
        }).join('');
        
        container.innerHTML = goalsHtml + `
            <div class="mindmap-child mindmap-add-child">
                <div class="mindmap-add-goal" onclick="showLinkGoalDialog('${projectID}','${phaseName}')"><span>➕</span> 关联目标</div>
                <div class="mindmap-add-goal" onclick="showLinkTaskDialog('${projectID}','${phaseName}')" style="margin-left:8px;"><span>➕</span> 关联任务</div>
            </div>`;
    }
    
    // 切换脑图目标下任务的展开/折叠
    function toggleMindmapGoalTasks(el, goalKey) {
        event.stopPropagation();
        const container = document.getElementById('mindmap-tasks-' + goalKey);
        const toggle = el.querySelector('.mindmap-toggle');
        if (container.classList.contains('expanded')) {
            container.classList.remove('expanded');
            if (toggle) toggle.classList.remove('open');
        } else {
            container.classList.add('expanded');
            if (toggle) toggle.classList.add('open');
        }
    }

    // ===== 动态阶段管理 =====
    // 显示添加阶段对话框（parentPhase 为空则添加顶层阶段，否则添加为子阶段）
    function showAddPhaseDialog(projectID, parentPhase) {
        const isSubPhase = !!parentPhase;
        const title = isSubPhase ? `添加子阶段（父：${parentPhase}）` : '添加阶段';
        const html = `
        <div class="modal-overlay" id="addPhaseOverlay" onclick="if(event.target===this)closeAddPhaseDialog()">
            <div class="modal-box" style="max-width:420px;">
                <div class="modal-header"><h3>${title}</h3><button class="modal-close" onclick="closeAddPhaseDialog()">✕</button></div>
                <div class="modal-body">
                    <div style="margin-bottom:12px;">
                        <label style="display:block;font-size:13px;margin-bottom:4px;">阶段名称 <span style="color:#ef4444;">*</span></label>
                        <input type="text" id="addPhaseName" placeholder="如：alpha_test, 灰度发布 等" style="width:100%;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);">
                    </div>
                    <div style="margin-bottom:12px;">
                        <label style="display:block;font-size:13px;margin-bottom:4px;">描述</label>
                        <textarea id="addPhaseDesc" rows="3" placeholder="阶段说明（可选）" style="width:100%;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);resize:vertical;"></textarea>
                    </div>
                    <div style="margin-bottom:12px;">
                        <label style="display:block;font-size:13px;margin-bottom:4px;">排序位置（越小越靠前，0=追加到末尾）</label>
                        <input type="number" id="addPhaseOrder" value="0" min="0" style="width:100%;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);">
                    </div>
                    <input type="hidden" id="addPhaseProjectID" value="${projectID}">
                    <input type="hidden" id="addPhaseParent" value="${parentPhase || ''}">
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="closeAddPhaseDialog()">取消</button>
                    <button class="btn btn-primary" onclick="submitAddPhase()">添加</button>
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', html);
    }
    
    function closeAddPhaseDialog() {
        const overlay = document.getElementById('addPhaseOverlay');
        if (overlay) overlay.remove();
    }
    
    async function submitAddPhase() {
        const projectID = document.getElementById('addPhaseProjectID').value;
        const name = document.getElementById('addPhaseName').value.trim();
        const description = document.getElementById('addPhaseDesc').value.trim();
        const order = parseInt(document.getElementById('addPhaseOrder').value) || 0;
        const parentPhase = document.getElementById('addPhaseParent').value.trim();
        
        if (!name) {
            showToast('阶段名称不能为空', 'error');
            return;
        }
        
        try {
            const body = {name, description, order};
            if (parentPhase) body.parent_phase = parentPhase;
            const resp = await fetch(`/api/projects/${projectID}/phases/add`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '添加失败');
            }
            showToast('阶段已添加！', 'success');
            closeAddPhaseDialog();
            // 刷新流程详情
            openProjectDetail(projectID);
        } catch(e) {
            showToast('添加失败: ' + e.message, 'error');
        }
    }
    
    // 删除阶段
    async function removePhase(projectID, phaseName) {
        const phaseLabelsLocal = {
            'idea': '创意', 'macro_supplement': '宏观', 'research': '调研',
            'mvp': 'MVP', 'p1': 'P1', 'p2': 'P2'
        };
        const label = phaseLabelsLocal[phaseName] || phaseName;
        if (!confirm(`确定要删除阶段「${label}」吗？此操作不可撤销。`)) return;
        
        try {
            const resp = await fetch(`/api/projects/${projectID}/phases/remove`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: phaseName})
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '删除失败');
            }
            showToast('阶段已删除', 'success');
            openProjectDetail(projectID);
        } catch(e) {
            showToast('删除失败: ' + e.message, 'error');
        }
    }
    
    // 显示编辑阶段对话框
    function showEditPhaseDialog(projectID, phaseName, description) {
        const phaseLabelsLocal = {
            'idea': '创意', 'macro_supplement': '宏观', 'research': '调研',
            'mvp': 'MVP', 'p1': 'P1', 'p2': 'P2'
        };
        const label = phaseLabelsLocal[phaseName] || phaseName;
        
        const html = `
        <div class="modal-overlay" id="editPhaseOverlay" onclick="if(event.target===this)closeEditPhaseDialog()">
            <div class="modal-box" style="max-width:420px;">
                <div class="modal-header"><h3>编辑阶段 - ${escapeHtml(label)}</h3><button class="modal-close" onclick="closeEditPhaseDialog()">✕</button></div>
                <div class="modal-body">
                    <div style="margin-bottom:12px;">
                        <label style="display:block;font-size:13px;margin-bottom:4px;">新名称（留空则不修改）</label>
                        <input type="text" id="editPhaseName" placeholder="${escapeHtml(phaseName)}" style="width:100%;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);">
                    </div>
                    <div style="margin-bottom:12px;">
                        <label style="display:block;font-size:13px;margin-bottom:4px;">新描述（留空则不修改）</label>
                        <textarea id="editPhaseDesc" rows="3" placeholder="${escapeHtml(description || '')}" style="width:100%;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);resize:vertical;">${escapeHtml(description || '')}</textarea>
                    </div>
                    <input type="hidden" id="editPhaseProjectID" value="${projectID}">
                    <input type="hidden" id="editPhaseOldName" value="${phaseName}">
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="closeEditPhaseDialog()">取消</button>
                    <button class="btn btn-primary" onclick="submitEditPhase()">保存</button>
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', html);
    }
    
    function closeEditPhaseDialog() {
        const overlay = document.getElementById('editPhaseOverlay');
        if (overlay) overlay.remove();
    }
    
    async function submitEditPhase() {
        const projectID = document.getElementById('editPhaseProjectID').value;
        const oldName = document.getElementById('editPhaseOldName').value;
        const newName = document.getElementById('editPhaseName').value.trim();
        const newDescription = document.getElementById('editPhaseDesc').value.trim();
        
        if (!newName && !newDescription) {
            showToast('至少修改一个字段', 'error');
            return;
        }
        
        try {
            const resp = await fetch(`/api/projects/${projectID}/phases/update`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: oldName, new_name: newName || '', new_description: newDescription || ''})
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '更新失败');
            }
            showToast('阶段信息已更新！', 'success');
            closeEditPhaseDialog();
            openProjectDetail(projectID);
        } catch(e) {
            showToast('更新失败: ' + e.message, 'error');
        }
    }

    // 加载 Phase 关联面板
    async function loadPhasePanel(projectID, phaseName) {
        currentPhaseName = phaseName;
        const phaseLabelsLocal = {
            'idea': '创意', 'macro_supplement': '宏观', 'research': '调研',
            'mvp': 'MVP', 'p1': 'P1', 'p2': 'P2'
        };
        const panel = document.getElementById('phasePanel');
        panel.style.display = 'block';
        document.getElementById('phasePanelContent').innerHTML = `<div style="font-size:14px;font-weight:600;margin-bottom:12px;">📌 ${phaseLabelsLocal[phaseName] || phaseName} 阶段详情</div><div class="skeleton" style="height:150px;border-radius:8px;"></div>`;
        
        try {
            const resp = await fetch(`/api/projects/${projectID}/phases/${phaseName}/overview`);
            const overview = await resp.json();
            renderPhasePanel(projectID, phaseName, overview);
        } catch(e) {
            document.getElementById('phasePanelContent').innerHTML = `<div style="text-align:center;color:var(--text-muted);padding:40px;">加载失败: ${e.message}</div>`;
        }
    }

    // 渲染 Phase 关联面板
    function renderPhasePanel(projectID, phaseName, overview) {
        const phaseLabels = {
            'idea': '创意', 'macro_supplement': '宏观', 'research': '调研',
            'mvp': 'MVP', 'p1': 'P1', 'p2': 'P2'
        };
        const progress = overview.progress || {};
        const goals = overview.goals || [];
        
        const totalGoals = progress.total_goals || 0;
        const completedGoals = progress.completed_goals || 0;
        const totalTasks = progress.total_tasks || 0;
        const completedTasks = progress.completed_tasks || 0;
        const percentage = progress.percentage || 0;

        // 审批操作区域（当 gate_status === 'pending' 时显示）
        const gateStatus = overview.gate_status || 'pending';
        const approvalHtml = gateStatus === 'pending' ? `
<div class="approval-panel" style="background:linear-gradient(135deg,#1e3a5f20,#1e3a5f10);border:1px solid #3b82f640;border-radius:8px;padding:16px;margin-bottom:16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <div>
            <div style="font-size:14px;font-weight:600;color:#f59e0b;">⏳ 等待审批</div>
            <div style="font-size:12px;color:var(--text-muted);margin-top:2px;">该阶段已提交审批，请审阅后操作</div>
        </div>
        <div style="display:flex;gap:8px;">
            <button class="btn-approve" onclick="showApprovalDialog('${projectID}','${phaseName}','approve')">✅ 通过</button>
            <button class="btn-revise" onclick="showApprovalDialog('${projectID}','${phaseName}','revise')">📝 修订</button>
            <button class="btn-reject" onclick="showApprovalDialog('${projectID}','${phaseName}','reject')">❌ 驳回</button>
        </div>
    </div>
    ${(overview.unmet_conditions && overview.unmet_conditions.length > 0) ? `
    <div style="background:#f59e0b15;border:1px solid #f59e0b40;border-radius:6px;padding:8px 12px;font-size:12px;color:#f59e0b;">
        ⚠️ 注意：还有 ${overview.unmet_conditions.length} 个准出条件未满足
    </div>` : ''}
</div>` : (gateStatus === 'approved' ? `
<div style="background:#10b98115;border:1px solid #10b98140;border-radius:8px;padding:12px 16px;margin-bottom:16px;display:flex;align-items:center;gap:8px;">
    <span style="font-size:18px;">✅</span>
    <div>
        <div style="font-size:13px;font-weight:600;color:#10b981;">已审批通过</div>
        ${overview.approved_by ? `<div style="font-size:12px;color:var(--text-muted);">审批人：${escapeHtml(overview.approved_by)}</div>` : ''}
    </div>
</div>` : (gateStatus === 'rejected' ? `
<div style="background:#ef444415;border:1px solid #ef444440;border-radius:8px;padding:12px 16px;margin-bottom:16px;display:flex;align-items:center;gap:8px;">
    <span style="font-size:18px;">❌</span>
    <div>
        <div style="font-size:13px;font-weight:600;color:#ef4444;">已被驳回</div>
        ${overview.reject_comment ? `<div style="font-size:12px;color:var(--text-muted);">${escapeHtml(overview.reject_comment)}</div>` : ''}
    </div>
</div>` : ''));

        // 准出条件
        const exitConditions = overview.exit_conditions || [];
        const exitConditionsHtml = exitConditions.length > 0 ? `
<div style="margin-bottom:16px;">
    <div style="font-size:13px;font-weight:500;margin-bottom:8px;">🚪 准出条件</div>
    ${exitConditions.map((cond, idx) => {
        const isMet = cond.is_met;
        const boundTask = cond.bound_task_id;
        const boundGoal = cond.bound_goal_id;
        return `
        <div style="display:flex;align-items:flex-start;gap:8px;padding:8px;border-radius:6px;background:var(--bg);margin-bottom:6px;border:1px solid ${isMet ? '#10b98130' : 'var(--border)'};"><div style="font-size:16px;flex-shrink:0;margin-top:1px;">${isMet ? '✅' : '⬜'}</div><div style="flex:1;"><div style="font-size:13px;${isMet ? 'text-decoration:line-through;color:var(--text-muted);' : ''}">${escapeHtml(cond.description)}</div>${boundTask ? `<div style="font-size:11px;margin-top:4px;"><span style="color:var(--text-muted);">关联任务：</span><span class="condition-task-link" onclick="openTaskDetailById('${boundTask}')" style="color:var(--accent);cursor:pointer;text-decoration:underline;">${escapeHtml(boundTask)}</span></div>` : ''}${boundGoal ? `<div style="font-size:11px;margin-top:2px;"><span style="color:var(--text-muted);">关联目标：</span><span style="color:#10b981;">${escapeHtml(boundGoal)}</span></div>` : ''}</div>${!boundTask && !boundGoal ? `<button class="btn-sm" style="flex-shrink:0;font-size:11px;" onclick="showBindConditionDialog('${projectID}','${phaseName}',${idx})">绑定</button>` : ''}</div>`;
    }).join('')}
</div>` : '';
        
        const goalsHtml = goals.map(goal => {
            const goalStatusColors = {'active': '#3b82f6', 'completed': '#10b981', 'pending': '#6b7280', 'cancelled': '#ef4444'};
            const goalStatusLabels = {'active': '进行中', 'completed': '已完成', 'pending': '待定', 'cancelled': '已取消'};
            const goalColor = goalStatusColors[goal.status] || '#6b7280';
            const goalStatusLabel = goalStatusLabels[goal.status] || goal.status;
            const tasks = goal.tasks || [];
            
            const tasksHtml = tasks.map(task => {
                const taskStatusColors = {'pending': '#6b7280', 'running': '#3b82f6', 'completed': '#10b981', 'failed': '#ef4444', 'blocked': '#f59e0b', 'interrupted': '#f97316'};
                const taskStatusLabels = {'pending': '待认领', 'running': '运行中', 'completed': '已完成', 'failed': '失败', 'blocked': '阻塞', 'interrupted': '中断', 'review': '审查中'};
                const taskColor = taskStatusColors[task.status] || '#6b7280';
                const taskStatusLabel = taskStatusLabels[task.status] || task.status;
                return `
                <div class="task-item" onclick="openTaskDetailById('${task.task_id}')" style="cursor:pointer;padding:6px 8px;border-radius:4px;background:var(--bg);margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;">
                    <div>
                        <span style="font-size:12px;">${escapeHtml(task.title || task.task_id)}</span>
                        ${task.claimed_by ? `<span style="font-size:11px;color:var(--text-muted);margin-left:8px;">@${task.claimed_by}</span>` : ''}
                    </div>
                    <span style="font-size:11px;padding:2px 6px;border-radius:3px;background:${taskColor}20;color:${taskColor};">${taskStatusLabel}</span>
                </div>`;
            }).join('');
            
            return `
            <div class="goal-item" style="border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;">
                <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" onclick="toggleGoalTasks(this)">
                    <div>
                        <span style="font-size:13px;font-weight:500;">${escapeHtml(goal.title || goal.goal_id)}</span>
                        <span style="font-size:11px;padding:2px 6px;border-radius:3px;background:${goalColor}20;color:${goalColor};margin-left:8px;">${goalStatusLabel}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-size:12px;color:var(--text-muted);">${goal.completed_tasks || 0}/${goal.total_tasks || 0} 任务</span>
                        <span style="font-size:12px;">▼</span>
                    </div>
                </div>
                <div class="goal-tasks" style="display:none;margin-top:8px;">
                    ${tasks.length > 0 ? tasksHtml : '<div style="font-size:12px;color:var(--text-muted);padding:4px;">暂无关联任务</div>'}
                </div>
            </div>`;
        }).join('');
        
        document.getElementById('phasePanelContent').innerHTML = `
        ${approvalHtml}
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <div style="font-size:14px;font-weight:600;">📌 ${phaseLabels[phaseName] || phaseName} 阶段</div>
            <div style="display:flex;gap:8px;">
                <button class="btn btn-sm" onclick="showLinkGoalDialog('${projectID}', '${phaseName}')">+ 关联目标</button>
                <button class="btn btn-sm" onclick="showLinkTaskDialog('${projectID}', '${phaseName}')">+ 关联任务</button>
            </div>
        </div>
        
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">
            <div style="text-align:center;padding:12px;background:var(--bg);border-radius:6px;">
                <div style="font-size:22px;font-weight:700;color:var(--accent);">${percentage.toFixed(0)}%</div>
                <div style="font-size:12px;color:var(--text-muted);">总进度</div>
            </div>
            <div style="text-align:center;padding:12px;background:var(--bg);border-radius:6px;">
                <div style="font-size:22px;font-weight:700;color:#10b981;">${completedGoals}/${totalGoals}</div>
                <div style="font-size:12px;color:var(--text-muted);">目标完成</div>
            </div>
            <div style="text-align:center;padding:12px;background:var(--bg);border-radius:6px;">
                <div style="font-size:22px;font-weight:700;color:#3b82f6;">${completedTasks}/${totalTasks}</div>
                <div style="font-size:12px;color:var(--text-muted);">任务完成</div>
            </div>
        </div>
        
        <div style="margin-bottom:16px;">
            <div style="font-size:13px;font-weight:500;margin-bottom:8px;">🎯 关联目标</div>
            ${goals.length > 0 ? goalsHtml : '<div style="text-align:center;color:var(--text-muted);padding:12px;">暂无关联目标，点击"关联目标"添加</div>'}
        </div>
        ${exitConditionsHtml}`;
    }

    // 展开/折叠 Goal 下的 Task 列表
    function toggleGoalTasks(header) {
        const tasksDiv = header.parentElement.querySelector('.goal-tasks');
        const arrow = header.querySelector('span:last-child');
        if (tasksDiv.style.display === 'none') {
            tasksDiv.style.display = 'block';
            arrow.textContent = '▲';
        } else {
            tasksDiv.style.display = 'none';
            arrow.textContent = '▼';
        }
    }

    // 通过 Task ID 打开 Task 详情（复用现有弹窗）
    function openTaskDetailById(taskID) {
        if (typeof openTaskDetail === 'function') {
            openTaskDetail(taskID);
        } else {
            showToast(`Task ID: ${taskID}`, 'info');
        }
    }

    // 关闭流程详情（返回流程列表）
    function closeProjectDetail() {
        document.getElementById('projectDetailPanel').style.display = 'none';
        document.getElementById('projectsListPanel').style.display = 'block';
        currentProjectID = null;
        currentPhaseName = null;
    }

    // 显示新建流程模态框
    function showCreateProjectModal() {
        document.getElementById('createProjectModal').style.display = 'flex';
    }

    // 关闭新建流程模态框
    function closeCreateProject() {
        document.getElementById('createProjectModal').style.display = 'none';
    }

    // 提交新建流程
    async function submitCreateProject() {
        const title = document.getElementById('newProjectTitle').value.trim();
        const description = document.getElementById('newProjectDesc').value.trim();
        const priority = parseInt(document.getElementById('newProjectPriority').value) || 5;
        
        if (!title || !description) {
            showToast('标题和描述不能为空', 'error');
            return;
        }
        
        try {
            const resp = await fetch('/api/projects', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({title, description, priority})
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '创建失败');
            }
            showToast('流程创建成功！', 'success');
            closeCreateProject();
            loadProjects();
        } catch(e) {
            showToast('创建失败: ' + e.message, 'error');
        }
    }

    // 显示关联 Goal 对话框
    async function showLinkGoalDialog(projectID, phaseName) {
        // 弹出目标列表选择弹窗
        const html = `
        <div class="modal-overlay" id="linkGoalOverlay" onclick="if(event.target===this)closeLinkGoalDialog()">
            <div class="modal-box" style="max-width:520px;">
                <div class="modal-header"><h3>关联目标到阶段</h3><button class="modal-close" onclick="closeLinkGoalDialog()">✕</button></div>
                <div class="modal-body">
                    <input type="text" id="linkGoalSearch" placeholder="🔍 搜索目标..." oninput="filterLinkGoalList()" 
                        style="width:100%;padding:8px 12px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);margin-bottom:10px;">
                    <div id="linkGoalList" style="max-height:340px;overflow-y:auto;">
                        <div style="text-align:center;padding:20px;color:var(--text-muted);">加载中...</div>
                    </div>
                    <input type="hidden" id="linkGoalProjectID" value="${projectID}">
                    <input type="hidden" id="linkGoalPhaseName" value="${phaseName}">
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', html);
        
        // 加载目标列表
        try {
            const resp = await fetch('/api/goals');
            if (!resp.ok) throw new Error('获取目标列表失败');
            const goals = await resp.json();
            window._linkGoalData = goals || [];
            renderLinkGoalList(goals);
        } catch(e) {
            document.getElementById('linkGoalList').innerHTML = `<div style="text-align:center;padding:20px;color:#ef4444;">加载失败: ${e.message}</div>`;
        }
    }
    
    function closeLinkGoalDialog() {
        const overlay = document.getElementById('linkGoalOverlay');
        if (overlay) overlay.remove();
    }
    
    function filterLinkGoalList() {
        const keyword = (document.getElementById('linkGoalSearch').value || '').toLowerCase();
        const goals = (window._linkGoalData || []).filter(g => {
            const title = (g.title || '').toLowerCase();
            const id = (g.id || '').toLowerCase();
            return title.includes(keyword) || id.includes(keyword);
        });
        renderLinkGoalList(goals);
    }
    
    function renderLinkGoalList(goals) {
        const container = document.getElementById('linkGoalList');
        if (!goals || goals.length === 0) {
            container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">暂无可选目标</div>';
            return;
        }
        const goalStatusLabels = {'active': '进行中', 'completed': '已完成', 'pending': '待定', 'cancelled': '已取消'};
        const goalStatusColors = {'active': '#3b82f6', 'completed': '#10b981', 'pending': '#6b7280', 'cancelled': '#ef4444'};
        
        container.innerHTML = goals.map(g => {
            const statusLabel = goalStatusLabels[g.status] || g.status;
            const statusColor = goalStatusColors[g.status] || '#6b7280';
            return `
            <div class="link-select-item" onclick="selectLinkGoal('${g.id}')">
                <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:0;">
                    <span>🎯</span>
                    <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(g.title || g.id)}</span>
                    <span style="font-size:11px;padding:2px 6px;border-radius:4px;background:${statusColor}20;color:${statusColor};flex-shrink:0;">${statusLabel}</span>
                </div>
                <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${g.id}</div>
            </div>`;
        }).join('');
    }
    
    async function selectLinkGoal(goalID) {
        const projectID = document.getElementById('linkGoalProjectID').value;
        const phaseName = document.getElementById('linkGoalPhaseName').value;
        
        try {
            const resp = await fetch(`/api/projects/${projectID}/phases/${phaseName}/link-goal`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({goal_id: goalID})
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '关联失败');
            }
            showToast('目标关联成功！', 'success');
            closeLinkGoalDialog();
            // 刷新脑图阶段
            openProjectDetail(projectID);
        } catch(e) {
            showToast('关联失败: ' + e.message, 'error');
        }
    }

    // 显示关联 Task 对话框（列表选择）
    async function showLinkTaskDialog(projectID, phaseName) {
        const html = `
        <div class="modal-overlay" id="linkTaskOverlay" onclick="if(event.target===this)closeLinkTaskDialog()">
            <div class="modal-box" style="max-width:520px;">
                <div class="modal-header"><h3>关联任务到阶段</h3><button class="modal-close" onclick="closeLinkTaskDialog()">✕</button></div>
                <div class="modal-body">
                    <input type="text" id="linkTaskSearch" placeholder="🔍 搜索任务..." oninput="filterLinkTaskList()" 
                        style="width:100%;padding:8px 12px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);margin-bottom:10px;">
                    <div id="linkTaskList" style="max-height:340px;overflow-y:auto;">
                        <div style="text-align:center;padding:20px;color:var(--text-muted);">加载中...</div>
                    </div>
                    <input type="hidden" id="linkTaskProjectID" value="${projectID}">
                    <input type="hidden" id="linkTaskPhaseName" value="${phaseName}">
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', html);
        
        // 加载任务列表
        try {
            const resp = await fetch('/api/tasks');
            if (!resp.ok) throw new Error('获取任务列表失败');
            const tasks = await resp.json();
            window._linkTaskData = tasks || [];
            renderLinkTaskList(tasks);
        } catch(e) {
            document.getElementById('linkTaskList').innerHTML = `<div style="text-align:center;padding:20px;color:#ef4444;">加载失败: ${e.message}</div>`;
        }
    }
    
    function closeLinkTaskDialog() {
        const overlay = document.getElementById('linkTaskOverlay');
        if (overlay) overlay.remove();
    }
    
    function filterLinkTaskList() {
        const keyword = (document.getElementById('linkTaskSearch').value || '').toLowerCase();
        const tasks = (window._linkTaskData || []).filter(t => {
            const title = (t.title || '').toLowerCase();
            const id = (t.id || '').toLowerCase();
            const goalId = (t.goal_id || '').toLowerCase();
            return title.includes(keyword) || id.includes(keyword) || goalId.includes(keyword);
        });
        renderLinkTaskList(tasks);
    }
    
    function renderLinkTaskList(tasks) {
        const container = document.getElementById('linkTaskList');
        if (!tasks || tasks.length === 0) {
            container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);">暂无可选任务</div>';
            return;
        }
        const taskStatusLabels = {'pending': '待认领', 'running': '运行中', 'completed': '已完成', 'failed': '失败', 'blocked': '阻塞', 'interrupted': '中断', 'review': '审查中'};
        const taskStatusColors = {'pending': '#6b7280', 'running': '#3b82f6', 'completed': '#10b981', 'failed': '#ef4444', 'blocked': '#f59e0b', 'interrupted': '#f97316', 'review': '#8b5cf6'};
        
        container.innerHTML = tasks.map(t => {
            const statusLabel = taskStatusLabels[t.status] || t.status;
            const statusColor = taskStatusColors[t.status] || '#6b7280';
            return `
            <div class="link-select-item" onclick="selectLinkTask('${t.id}', '${t.goal_id || ''}')">
                <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:0;">
                    <span>📋</span>
                    <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(t.title || t.id)}</span>
                    <span style="font-size:11px;padding:2px 6px;border-radius:4px;background:${statusColor}20;color:${statusColor};flex-shrink:0;">${statusLabel}</span>
                </div>
                <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${t.id}${t.goal_id ? ' · 目标: ' + t.goal_id : ''}</div>
            </div>`;
        }).join('');
    }
    
    async function selectLinkTask(taskID, goalID) {
        const projectID = document.getElementById('linkTaskProjectID').value;
        const phaseName = document.getElementById('linkTaskPhaseName').value;
        
        try {
            const resp = await fetch(`/api/projects/${projectID}/phases/${phaseName}/link-task`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({task_id: taskID, goal_id: goalID})
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '关联失败');
            }
            showToast('任务关联成功！', 'success');
            closeLinkTaskDialog();
            openProjectDetail(projectID);
        } catch(e) {
            showToast('关联失败: ' + e.message, 'error');
        }
    }

    // 切换到 projects 视图时自动加载
    document.addEventListener('DOMContentLoaded', () => {
        const navBtns = document.querySelectorAll('.nav-btn[data-view="projects"]');
        navBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                setTimeout(loadProjects, 100);
            });
        });
        // 加载待审批数量徽章
        loadApprovalBadge();
    });


    // ==================== 审批操作 ====================

    // 显示审批对话框
    function showApprovalDialog(projectID, phaseName, action) {
        document.getElementById('approvalProjectID').value = projectID;
        document.getElementById('approvalPhaseName').value = phaseName;
        document.getElementById('approvalAction').value = action;
        document.getElementById('approvalComment').value = '';
        document.getElementById('revisionItems').value = '';
        
        const titles = { approve: '✅ 审批通过', reject: '❌ 驳回阶段', revise: '📝 请求修订' };
        const btnColors = { approve: '#10b981', reject: '#ef4444', revise: '#f59e0b' };
        
        document.getElementById('approvalDialogTitle').textContent = titles[action] || '审批操作';
        const submitBtn = document.getElementById('approvalSubmitBtn');
        submitBtn.textContent = titles[action] || '提交';
        submitBtn.style.background = btnColors[action] || '';
        
        // 修订和驳回时显示修订要点输入框
        document.getElementById('revisionItemsGroup').style.display = 
            (action === 'revise' || action === 'reject') ? 'block' : 'none';
        
        document.getElementById('approvalDialog').style.display = 'flex';
        setTimeout(() => document.getElementById('approvalComment').focus(), 100);
    }

    // 关闭审批对话框
    function closeApprovalDialog() {
        document.getElementById('approvalDialog').style.display = 'none';
    }

    // 提交审批
    async function submitApproval() {
        const projectID = document.getElementById('approvalProjectID').value;
        const phaseName = document.getElementById('approvalPhaseName').value;
        const action = document.getElementById('approvalAction').value;
        const comment = document.getElementById('approvalComment').value.trim();
        
        if (!comment) {
            showToast('请填写审批意见', 'error');
            return;
        }
        
        const revisionText = document.getElementById('revisionItems').value.trim();
        const revisionItems = revisionText ? revisionText.split('\n').filter(s => s.trim()) : [];
        
        const endpoints = {
            approve: `/api/projects/${projectID}/gates/${phaseName}/approve`,
            reject: `/api/projects/${projectID}/gates/${phaseName}/reject`,
            revise: `/api/projects/${projectID}/gates/${phaseName}/revise`
        };
        
        const bodies = {
            approve: { comment, approved_by: 'human' },
            reject: { comment, revision_items: revisionItems },
            revise: { comment, revision_items: revisionItems }
        };
        
        try {
            const resp = await fetch(endpoints[action], {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(bodies[action])
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '操作失败');
            }
            
            const actionLabels = { approve: '审批通过', reject: '已驳回', revise: '已请求修订' };
            showToast(`${actionLabels[action]}！`, 'success');
            closeApprovalDialog();
            
            // 刷新流程详情和 Phase 面板
            if (currentProjectID) {
                openProjectDetail(currentProjectID);
            }
            loadApprovalBadge();
            loadProjects();
        } catch(e) {
            showToast('操作失败: ' + e.message, 'error');
        }
    }

    // 显示绑定条件对话框
    function showBindConditionDialog(projectID, phaseName, conditionIndex) {
        document.getElementById('bindCondProjectID').value = projectID;
        document.getElementById('bindCondPhaseName').value = phaseName;
        document.getElementById('bindCondIndex').value = conditionIndex;
        document.getElementById('bindCondTaskID').value = '';
        document.getElementById('bindCondGoalID').value = '';
        document.getElementById('bindConditionDialog').style.display = 'flex';
    }

    // 关闭绑定条件对话框
    function closeBindConditionDialog() {
        document.getElementById('bindConditionDialog').style.display = 'none';
    }

    // 提交绑定条件
    async function submitBindCondition() {
        const projectID = document.getElementById('bindCondProjectID').value;
        const phaseName = document.getElementById('bindCondPhaseName').value;
        const conditionIndex = parseInt(document.getElementById('bindCondIndex').value);
        const taskID = document.getElementById('bindCondTaskID').value.trim();
        const goalID = document.getElementById('bindCondGoalID').value.trim();
        
        if (!taskID && !goalID) {
            showToast('请至少填写 Task ID 或 Goal ID', 'error');
            return;
        }
        
        try {
            const resp = await fetch(`/api/projects/${projectID}/phases/${phaseName}/bind-condition`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ condition_index: conditionIndex, task_id: taskID, goal_id: goalID })
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '绑定失败');
            }
            
            showToast('条件绑定成功！', 'success');
            closeBindConditionDialog();
            
            // 刷新 Phase 面板
            if (currentProjectID && currentPhaseName) {
                loadPhasePanel(currentProjectID, currentPhaseName);
            }
        } catch(e) {
            showToast('绑定失败: ' + e.message, 'error');
        }
    }

    // 加载待审批数量徽章
    async function loadApprovalBadge() {
        try {
            const resp = await fetch('/api/projects/pending-approvals');
            if (!resp.ok) return;
            const data = await resp.json();
            const badge = document.getElementById('approvalBadge');
            if (badge) {
                if (data.count > 0) {
                    badge.textContent = data.count;
                    badge.style.display = 'inline-block';
                } else {
                    badge.style.display = 'none';
                }
            }
        } catch(e) {
            // 静默失败
        }
    }

    // ===== 流程字段编辑功能 =====
    function toggleEditField(prefix, projectID, fieldName) {
        const display = document.getElementById(prefix + 'Display');
        const edit = document.getElementById(prefix + 'Edit');
        if (edit.style.display === 'none') {
            display.style.display = 'none';
            edit.style.display = 'block';
        } else {
            cancelEditField(prefix);
        }
    }

    function cancelEditField(prefix) {
        const display = document.getElementById(prefix + 'Display');
        const edit = document.getElementById(prefix + 'Edit');
        display.style.display = 'block';
        edit.style.display = 'none';
    }

    async function saveProjectField(projectID, fieldName, inputId) {
        const input = document.getElementById(inputId);
        const value = input.value.trim();
        try {
            const resp = await fetch('/api/projects/' + projectID, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fields: { [fieldName]: value } })
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '保存失败');
            }
            showToast('保存成功', 'success');
            // 刷新流程详情
            openProjectDetail(projectID);
        } catch(e) {
            showToast('保存失败: ' + e.message, 'error');
        }
    }

    // ===== 任务队列视图 =====
    let taskViewData = [];
    let taskViewFilter = 'all';
    let taskViewGoalFilter = 'all';
    let taskViewShouldCollapseGoals = false;
    let taskViewSearchText = '';

    async function loadTaskView() {
        const body = document.getElementById('taskViewBody');
        if (body) body.innerHTML = '<div class="task-empty">加载中...</div>';
        try {
            const resp = await fetch('/api/tasks');
            const data = await resp.json();
            taskViewData = data || [];
            renderTaskView();
        } catch(e) {
            if (body) body.innerHTML = '<div class="task-empty">获取失败: ' + e.message + '</div>';
        }
    }

    function filterTaskViewStatus(status, btn) {
        taskViewFilter = status;
        taskViewShouldCollapseGoals = false;
        document.getElementById('taskViewFilters').querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderTaskView();
    }

    function filterTaskViewGoals(goalStatus, btn) {
        taskViewGoalFilter = goalStatus;
        taskViewShouldCollapseGoals = true;
        document.getElementById('taskViewGoalFilters').querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderTaskView();
    }

    function filterTaskView() {
        taskViewSearchText = (document.getElementById('taskViewSearch').value || '').toLowerCase();
        renderTaskView();
    }

    function renderTaskView() {
        const body = document.getElementById('taskViewBody');
        if (!body) return;

        const filtered = taskViewFilter === 'all' ? taskViewData : taskViewData.filter(t => t.status === taskViewFilter);
        const counts = {};
        taskViewData.forEach(t => { counts[t.status] = (counts[t.status]||0)+1; });

        // 统计目标组状态计数
        const goalStatusCounts = {};
        const seenGoals = {};
        taskViewData.forEach(t => {
            const gid = t.goal_id || '__ungrouped__';
            if (!seenGoals[gid]) {
                seenGoals[gid] = true;
                const gs = t.goal_status || '';
                if (gs) goalStatusCounts[gs] = (goalStatusCounts[gs] || 0) + 1;
            }
        });

        // 更新目标组筛选按钮计数
        var tvGoalFilters = document.getElementById('taskViewGoalFilters');
        if (tvGoalFilters) {
            tvGoalFilters.querySelectorAll('.filter-btn').forEach(btn => {
                const gs = btn.dataset.goalStatus;
                if (gs === 'all') {
                    btn.textContent = '全部 (' + Object.values(goalStatusCounts).reduce((a,b) => a+b, 0) + ')';
                    return;
                }
                const c = goalStatusCounts[gs] || 0;
                const labels = {active:'▶ 进行中',pending:'⏸ 暂停',completed:'✅ 已完成',cancelled:'✕ 已取消'};
                btn.textContent = (labels[gs]||gs) + ' (' + c + ')';
            });
        }

        const countInfo = document.getElementById('taskViewCountInfo');
        if (countInfo) countInfo.textContent = '（共 '+taskViewData.length+' 个任务'+(taskViewFilter !== 'all' ? '，筛选 '+filtered.length+' 个' : '')+'）';

        // 更新任务筛选按钮计数
        var tvFilters = document.getElementById('taskViewFilters');
        if (tvFilters) {
            tvFilters.querySelectorAll('.filter-btn').forEach(btn => {
                const st = btn.dataset.status;
                if (st === 'all') return;
                const c = counts[st] || 0;
                const labels = {pending:'⏳ 待认领',running:'🔄 运行中',completed:'✅ 已完成',failed:'❌ 失败',blocked:'🚫 阻塞',interrupted:'⚡ 中断',review:'🔍 审查中'};
                btn.textContent = (labels[st]||st) + ' (' + c + ')';
            });
        }

        // 搜索过滤
        let searchFiltered = filtered;
        if (taskViewSearchText) {
            searchFiltered = filtered.filter(t =>
                (t.title || '').toLowerCase().includes(taskViewSearchText) ||
                (t.id || '').toLowerCase().includes(taskViewSearchText) ||
                (t.description || '').toLowerCase().includes(taskViewSearchText)
            );
        }

        if (searchFiltered.length === 0) {
            body.innerHTML = '<div class="task-empty" style="padding:40px;text-align:center;color:var(--text-muted);">暂无匹配的任务</div>';
            return;
        }

        // 按 Goal 分组
        const groups = {}, order = [];
        searchFiltered.forEach(t => {
            const gid = t.goal_id || '__ungrouped__';
            if (!groups[gid]) {
                groups[gid] = { goalId:t.goal_id||'', goalTitle:t.goal_title||'未关联项目', goalStatus:t.goal_status||'', tasks:[] };
                order.push(gid);
            }
            groups[gid].tasks.push(t);
        });

        // 按目标组状态过滤
        const filteredOrder = taskViewGoalFilter === 'all' ? order : order.filter(gid => {
            return groups[gid].goalStatus === taskViewGoalFilter;
        });

        if (filteredOrder.length === 0) {
            body.innerHTML = '<div class="task-empty" style="padding:40px;text-align:center;color:var(--text-muted);">当前目标组筛选条件下暂无任务</div>';
            return;
        }

        // 点击目标组按钮时收缩，点击任务按钮时展开
        const shouldCollapse = taskViewShouldCollapseGoals;

        let html = '';
        filteredOrder.forEach(gid => {
            const g = groups[gid];
            const cnt = g.tasks.length;
            const avg = g.tasks.reduce((s,t) => s + (t.progress||0), 0) / cnt;
            const sc = {};
            g.tasks.forEach(t => { sc[t.status] = (sc[t.status]||0)+1; });
            const summary = Object.entries(sc).map(([k,v]) => { const n = {pending:'待认领',running:'运行中',completed:'已完成',failed:'失败',blocked:'阻塞',interrupted:'中断',review:'审查中'}; return (n[k]||k)+' '+v; }).join(' · ');
            const reviewCount = sc['review'] || 0;
            const progressColor = avg >= 100 ? 'var(--green)' : avg >= 50 ? 'var(--yellow)' : 'var(--accent)';

            html += '<div class="goal-group">';
            html += '<div class="goal-group-header" onclick="toggleGoalGroup(this)">';
            html += '<div class="goal-group-left">';
            html += '<span class="goal-group-arrow'+(shouldCollapse?' collapsed':'')+'">'+(shouldCollapse?'\u25b6':'\u25bc')+'</span>';
            html += '<span class="goal-group-icon">🎯</span>';
            html += '<span class="goal-group-title">'+esc(g.goalTitle)+'</span>';
            html += getGoalStatusBadge(g.goalStatus);
            // 目标状态切换按钮
            html += '<span class="goal-status-actions" onclick="event.stopPropagation()">';
            var goalStatuses = [{key:'active',label:'▶ 进行中',cls:'st-active'},{key:'pending',label:'⏸ 暂停',cls:'st-pending'},{key:'completed',label:'✓ 完成',cls:'st-completed'},{key:'cancelled',label:'✕ 取消',cls:'st-cancelled'}];
            goalStatuses.forEach(function(gs){
                var isCurrent = g.goalStatus === gs.key;
                html += '<button class="btn-goal-status '+gs.cls+(isCurrent?' st-current':'')+'" ';
                if (!isCurrent) html += 'onclick="updateGoalStatusFromTask(\''+esc(g.goalId)+'\',\''+gs.key+'\')" ';
                html += 'title="'+(isCurrent?'当前状态':'切换到'+gs.label)+'">'+gs.label+'</button>';
            });
            html += '</span>';
            // 全部审查按钮
            var allCompleted = g.tasks.length > 0 && g.tasks.every(function(t){ return t.status === 'completed'; });
            if (allCompleted) {
                html += '<button class="btn-review-all" onclick="event.stopPropagation();reviewAllTasks(\''+esc(g.goalId)+'\',\''+esc(g.goalTitle)+'\')" title="将所有任务切换为审查状态">🔍 全部审查</button>';
            }
            // review批量操作按钮
            if (reviewCount > 0) {
                html += '<span class="review-batch-actions" onclick="event.stopPropagation()" style="display:inline-flex;align-items:center;gap:4px;margin-left:4px;">';
                html += '<button class="btn-review-pass" onclick="reviewBatchPass(\''+esc(g.goalId)+'\',\''+esc(g.goalTitle)+'\')" title="批量通过所有review任务" style="background:var(--green);color:#fff;border:none;border-radius:4px;padding:2px 8px;font-size:11px;cursor:pointer;font-weight:600;">✅ 全部通过 ('+reviewCount+')</button>';
                html += '<button class="btn-review-fail" onclick="reviewBatchFail(\''+esc(g.goalId)+'\',\''+esc(g.goalTitle)+'\')" title="批量拒绝所有review任务" style="background:var(--red);color:#fff;border:none;border-radius:4px;padding:2px 8px;font-size:11px;cursor:pointer;font-weight:600;">❌ 全部拒绝 ('+reviewCount+')</button>';
                html += '</span>';
            }
            html += '<span class="goal-group-count">'+cnt+' 个任务</span>';
            html += '<button class="btn-delete-group" onclick="event.stopPropagation();deleteTasksByGoal(\''+esc(g.goalId)+'\',\''+esc(g.goalTitle)+'\')" title="删除全部">🗑</button>';
            html += '</div><div class="goal-group-right">';
            html += '<span class="goal-group-summary">'+summary+'</span>';
            html += '<div class="goal-progress-mini"><div class="goal-progress-mini-fill" style="width:'+avg.toFixed(0)+'%;background:'+progressColor+';"></div></div>';
            html += '<span style="font-size:10px;color:var(--text-muted);">'+avg.toFixed(0)+'%</span>';
            html += '</div></div>';

            // ===== 树状/瀑布结构渲染 =====
            html += '<div class="goal-group-body" style="padding:8px 12px;'+(shouldCollapse?'display:none;':'')+'">';

            // 构建依赖图 → 拓扑排序 → 层级渲染
            const taskMap = {};
            g.tasks.forEach(t => { taskMap[t.id] = t; });
            const depOf = {};
            const depOn = {};
            g.tasks.forEach(t => {
                depOn[t.id] = (t.dependencies || []).filter(d => taskMap[d]);
                depOn[t.id].forEach(d => {
                    if (!depOf[d]) depOf[d] = [];
                    depOf[d].push(t.id);
                });
            });

            // 拓扑排序获取层级
            const levels = {};
            const inDegree = {};
            g.tasks.forEach(t => { inDegree[t.id] = (depOn[t.id] || []).length; });
            let queue = g.tasks.filter(t => inDegree[t.id] === 0).map(t => t.id);
            let level = 0;
            const ordered = [];
            while (queue.length > 0) {
                const next = [];
                queue.forEach(id => {
                    levels[id] = level;
                    ordered.push(id);
                    (depOf[id] || []).forEach(child => {
                        inDegree[child]--;
                        if (inDegree[child] === 0) next.push(child);
                    });
                });
                queue = next;
                level++;
            }
            g.tasks.forEach(t => { if (!ordered.includes(t.id)) { levels[t.id] = level; ordered.push(t.id); } });

            // 树状表头
            html += '<div style="display:flex;align-items:center;padding:6px 8px;border-bottom:2px solid var(--border-light);font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">';
            html += '<div style="width:36px;flex-shrink:0;">层</div>';
            html += '<div style="width:110px;flex-shrink:0;">ID</div>';
            html += '<div style="flex:1;min-width:0;">任务</div>';
            html += '<div style="width:95px;flex-shrink:0;">状态</div>';
            html += '<div style="width:110px;flex-shrink:0;">进度</div>';
            html += '<div style="width:80px;flex-shrink:0;">依赖</div>';
            html += '<div style="width:80px;flex-shrink:0;">类型</div>';
            html += '<div style="width:80px;flex-shrink:0;">执行者</div>';
            html += '<div style="width:50px;flex-shrink:0;text-align:center;">优先</div>';
            html += '<div style="width:50px;flex-shrink:0;text-align:center;">难度</div>';
            html += '<div style="width:70px;flex-shrink:0;text-align:center;">操作</div>';
            html += '</div>';

            ordered.forEach((tid, idx) => {
                const t = taskMap[tid];
                if (!t) return;
                const lvl = levels[tid] || 0;
                const p = t.progress || 0;
                const deps = depOn[tid] || [];
                const children = depOf[tid] || [];
                const desc = t.description ? t.description.substring(0,40)+(t.description.length>40?'…':'') : '';

                html += '<div class="tree-task-row">';

                // 树状缩进 + 连接线
                html += '<div style="width:'+(36 + lvl*24)+'px;flex-shrink:0;display:flex;align-items:center;justify-content:flex-end;padding-right:6px;">';
                if (lvl === 0) {
                    html += '<span style="width:8px;height:8px;border-radius:50%;background:var(--green);flex-shrink:0;" title="根任务"></span>';
                } else {
                    html += '<span style="display:inline-flex;align-items:center;">';
                    for (let l = 0; l < lvl - 1; l++) {
                        html += '<span style="width:24px;border-left:2px solid var(--border);height:28px;display:inline-block;"></span>';
                    }
                    html += '<span style="display:inline-flex;align-items:center;">';
                    html += '<span style="width:24px;height:28px;border-left:2px solid var(--border);border-bottom:2px solid var(--border);border-radius:0 0 0 6px;display:inline-block;vertical-align:middle;margin-bottom:14px;"></span>';
                    html += '<span style="width:6px;height:6px;border-radius:50%;background:var(--purple);flex-shrink:0;" title="子任务 (层级 '+lvl+')"></span>';
                    html += '</span></span>';
                }
                html += '</div>';

                // 内容行
                html += '<div style="flex:1;min-width:0;display:flex;align-items:center;gap:4px;font-size:12px;padding:4px 0;">';

                // ID
                html += '<div style="width:110px;flex-shrink:0;"><span style="color:var(--accent);font-size:10px;font-family:monospace;cursor:pointer;" title="点击复制" onclick="copyId(this,\''+esc(t.id)+'\')">'+esc(t.id)+'</span></div>';

                // 任务名 + 依赖标签
                html += '<div style="flex:1;min-width:0;">';
                html += '<div class="task-title" style="font-size:12px;">'+esc(t.title||t.id);
                if (t.parent_task_id) {
                    var parentTask = taskMap[t.parent_task_id];
                    var parentName = parentTask ? parentTask.title : t.parent_task_id.substring(0,12)+'…';
                    html += ' <span style="font-size:9px;background:var(--purple);color:#fff;padding:1px 5px;border-radius:3px;margin-left:4px;" title="父任务: '+esc(parentName)+'">🔀 子任务</span>';
                }
                if (t.review_result === 'passed') {
                    var reviewTime = t.reviewed_at ? ' · '+(t.reviewed_at||'').substring(0,10) : '';
                    var reviewTip = (t.reviewed_by ? '审查人: '+t.reviewed_by : '') + (t.review_comment ? '\n意见: '+t.review_comment : '') + reviewTime;
                    html += ' <span style="font-size:9px;background:var(--green);color:#fff;padding:1px 6px;border-radius:3px;margin-left:4px;" title="'+esc(reviewTip)+'">✅ 通过'+reviewTime+'</span>';
                } else if (t.review_result === 'failed') {
                    var reviewTime2 = t.reviewed_at ? ' · '+(t.reviewed_at||'').substring(0,10) : '';
                    var reviewTip2 = (t.reviewed_by ? '审查人: '+t.reviewed_by : '') + (t.review_comment ? '\n意见: '+t.review_comment : '') + reviewTime2;
                    html += ' <span style="font-size:9px;background:var(--red);color:#fff;padding:1px 6px;border-radius:3px;margin-left:4px;" title="'+esc(reviewTip2)+'">❌ 拒绝'+reviewTime2+'</span>';
                }
                if (deps.length > 0) {
                    deps.forEach(did => {
                        const dt = taskMap[did];
                        const depName = dt ? dt.title : did.substring(0,10)+'…';
                        const depStatus = dt ? dt.status : 'unknown';
                        const depDone = depStatus === 'completed';
                    html += ' <span class="tree-dep-label" title="依赖: '+esc(depName)+' ('+depStatus+')" style="'+(depDone?'opacity:0.5;text-decoration:line-through;':'')+'">← '+esc(depName.substring(0,12))+(depDone?' ✓':' ⏳')+' <span class="dep-remove-btn" title="移除此依赖" onclick="event.stopPropagation();removeDependency(\''+esc(t.id)+'\',\''+esc(did)+'\')">&times;</span></span>';
                    });
                }
                html += '</div>';
                if (desc) html += '<div class="task-desc" title="'+esc(t.description)+'">'+esc(desc)+'</div>';
                html += '</div>';

                // 状态（可修改下拉）
                html += '<div style="width:95px;flex-shrink:0;">'+getStatusSelect(t.id, t.status)+'</div>';

                // 进度
                html += '<div style="width:110px;flex-shrink:0;display:flex;align-items:center;gap:4px;">';
                html += '<div class="task-progress-bar"><div class="task-progress-fill '+getProgressColor(p)+'" style="width:'+p+'%"></div></div>';
                html += '<span style="font-size:10px;color:var(--text-muted);">'+p.toFixed(0)+'%</span></div>';

                // 依赖数
                html += '<div style="width:80px;flex-shrink:0;">';
                if (deps.length > 0 || children.length > 0) {
                    html += '<span style="font-size:10px;color:var(--purple);">';
                    if (deps.length > 0) html += '↑'+deps.length;
                    if (deps.length > 0 && children.length > 0) html += ' ';
                    if (children.length > 0) html += '<span style="color:var(--green);">↓'+children.length+'</span>';
                    html += '</span>';
                } else {
                    html += '<span style="font-size:10px;color:var(--text-dimmed);">—</span>';
                }
                html += '</div>';

                // 类型
                html += '<div style="width:80px;flex-shrink:0;font-size:11px;color:var(--text-muted);">'+esc(t.skill_type||'—')+'</div>';

                // 执行者
                html += '<div style="width:80px;flex-shrink:0;font-size:11px;color:var(--text-muted);">'+esc(t.claimed_by||'—')+'</div>';

                // 优先级
                html += '<div style="width:50px;flex-shrink:0;text-align:center;"><span style="color:var(--yellow);font-size:11px;font-weight:700;">'+(t.priority||0)+'</span></div>';

                // 难度标签
                var diff = t.difficulty || 5;
                var diffColor = diff <= 3 ? 'var(--green)' : diff <= 6 ? 'var(--yellow)' : diff <= 9 ? 'var(--orange,#f0883e)' : 'var(--red)';
                var diffLabel = diff <= 3 ? '简单' : diff <= 6 ? '中等' : diff <= 9 ? '困难' : '极难';
                html += '<div style="width:50px;flex-shrink:0;text-align:center;"><span style="color:'+diffColor+';font-size:10px;font-weight:700;" title="难度: '+diff+'/10">'+diffLabel+'</span></div>';

                // 操作
                html += '<div style="width:70px;flex-shrink:0;text-align:center;"><span class="btn-action-group">';
                html += '<button class="btn-edit" title="编辑" onclick="event.stopPropagation();openTaskEdit(\''+esc(t.id)+'\')">✏️</button>';
                html += '<button class="btn-delete" title="删除" onclick="event.stopPropagation();deleteTask(\''+esc(t.id)+'\',\''+esc(t.title||t.id)+'\')">🗑</button>';
                if (t.status === 'running') html += '<button class="btn-edit" title="拆分为子任务" onclick="event.stopPropagation();openSplitTask(\''+esc(t.id)+'\',\''+esc(t.title||t.id)+'\')" style="font-size:10px;">✂️</button>';
                html += '</span></div>';

                html += '</div></div>'; // 关闭内容行 + tree-task-row
            });

            html += '</div></div>'; // 关闭 goal-group-body + goal-group
        });

        if (!html) {
            body.innerHTML = '<div class="task-empty" style="padding:40px;text-align:center;color:var(--text-muted);">暂无匹配的任务</div>';
        } else {
            body.innerHTML = html;
        }
    }

    function getGoalStatusBadge(status) {
        const map = {
            'active': '<span class="badge badge-blue">▶ 进行中</span>',
            'pending': '<span class="badge badge-yellow">⏸ 暂停</span>',
            'completed': '<span class="badge badge-green">✅ 已完成</span>',
            'cancelled': '<span class="badge badge-gray">✕ 已取消</span>'
        };
        return map[status] || '';
    }

