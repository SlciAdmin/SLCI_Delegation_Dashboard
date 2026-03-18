/* ============================================
   SLCI Delegation Dashboard - Main JavaScript
   ============================================ */

// Theme Toggle
const themeToggle = document.getElementById('themeToggle');
const html = document.documentElement;
const savedTheme = localStorage.getItem('slci_theme') || 'light';
html.setAttribute('data-theme', savedTheme);

if(themeToggle) {
    themeToggle.addEventListener('click', () => {
        const newTheme = html.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        html.setAttribute('data-theme', newTheme);
        localStorage.setItem('slci_theme', newTheme);
        updateChartsTheme(newTheme);
    });
}

// 3D Tilt Effect for Cards
document.querySelectorAll('.card').forEach(card => {
    card.addEventListener('mousemove', (e) => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;
        const rotateX = ((y - centerY) / centerY) * -5;
        const rotateY = ((x - centerX) / centerX) * 5;
        card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(1.02)`;
    });
    
    card.addEventListener('mouseleave', () => {
        card.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) scale(1)';
    });
});

// Auto-hide flash messages
setTimeout(() => {
    document.querySelectorAll('.flash-message').forEach(msg => {
        msg.style.transition = 'opacity 0.5s';
        msg.style.opacity = '0';
        setTimeout(() => msg.remove(), 500);
    });
}, 5000);

// Chart.js Initialization
let charts = {};

function initCharts() {
    const ctxStatus = document.getElementById('statusChart');
    const ctxPerformance = document.getElementById('performanceChart');
    const theme = html.getAttribute('data-theme');
    const textColor = theme === 'dark' ? '#f1f5f9' : '#1e293b';
    const gridColor = theme === 'dark' ? '#334155' : '#e2e8f0';
    
    if (ctxStatus && window.chartData) {
        charts.status = new Chart(ctxStatus, {
            type: 'doughnut',
            data: {
                labels: window.chartData.status.labels,
                datasets: [{
                    data: window.chartData.status.data,
                    backgroundColor: window.chartData.status.colors
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        labels: { color: textColor }
                    }
                }
            }
        });
    }
    
    if (ctxPerformance && window.chartData) {
        charts.performance = new Chart(ctxPerformance, {
            type: 'bar',
            data: {
                labels: window.chartData.performance.labels,
                datasets: [{
                    label: 'On-Time Tasks',
                    data: window.chartData.performance.data,
                    backgroundColor: '#6366f1'
                }]
            },
            options: {
                responsive: true,
                scales: {
                    y: {
                        ticks: { color: textColor },
                        grid: { color: gridColor }
                    },
                    x: {
                        ticks: { color: textColor },
                        grid: { display: false }
                    }
                }
            }
        });
    }
}

function updateChartsTheme(theme) {
    if(window.chartData) {
        Object.values(charts).forEach(c => c.destroy());
        initCharts();
    }
}

// Delete Confirmation
function confirmDelete(url, name) {
    if(confirm(`⚠️ Are you sure you want to remove ${name}? This cannot be undone.`)) {
        window.location.href = url;
    }
}

// Handle delete click (for employee management)
function handleDeleteClick(button) {
    const container = button.closest('div[data-employee-id]');
    if (!container) return;
    
    const url = container.getAttribute('data-delete-url');
    const name = container.getAttribute('data-employee-name');
    
    if (confirm('⚠️ Are you sure you want to remove ' + name + '? This cannot be undone.')) {
        window.location.href = url;
    }
}

// Filter Logic for Tasks
function filterTasks() {
    const statusSelect = document.getElementById('filterStatus');
    if (!statusSelect) return;
    
    const status = statusSelect.value;
    const items = document.querySelectorAll('.task-item');
    
    items.forEach(item => {
        if (status === 'all' || item.classList.contains('status-' + status)) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
}

// Form Validation
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return true;
    
    const requiredFields = form.querySelectorAll('[required]');
    let isValid = true;
    
    requiredFields.forEach(field => {
        if (!field.value.trim()) {
            field.style.borderColor = 'var(--danger)';
            isValid = false;
        } else {
            field.style.borderColor = 'var(--gray-light)';
        }
    });
    
    return isValid;
}

// Real-time Search
function searchTasks(searchInput) {
    const query = searchInput.value.toLowerCase();
    const items = document.querySelectorAll('.task-item');
    
    items.forEach(item => {
        const title = item.querySelector('.task-title')?.textContent.toLowerCase() || '';
        const meta = item.querySelector('.task-meta')?.textContent.toLowerCase() || '';
        
        if (title.includes(query) || meta.includes(query)) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
}

// Notification Polling (Real-time updates)
function pollNotifications() {
    fetch('/api/notifications')
        .then(response => response.json())
        .then(data => {
            const unreadCount = data.length;
            const badge = document.getElementById('notifBadge');
            if (badge && unreadCount > 0) {
                badge.textContent = unreadCount;
                badge.style.display = 'inline-block';
            }
        })
        .catch(error => console.error('Notification error:', error));
}

// Poll every 30 seconds
setInterval(pollNotifications, 30000);

// Mark notification as read
function markAsRead(notifId) {
    fetch(`/api/notifications/${notifId}/read`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                pollNotifications();
            }
        });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    console.log('✅ SLCI Dashboard Loaded');
    
    // Initialize charts if on reports page
    if (document.getElementById('statusChart') || document.getElementById('performanceChart')) {
        initCharts();
    }
    
    // Initial notification poll
    pollNotifications();
    
    // Add form validation listeners
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!validateForm(this.id)) {
                e.preventDefault();
                alert('Please fill all required fields.');
            }
        });
    });
});

// Export function
function exportData(format) {
    window.location.href = `/admin/export_${format}`;
}

console.log('🚀 SLCI Professional Dashboard Initialized');