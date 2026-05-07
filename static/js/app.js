/**
 * Infra Monitor 前端脚本
 * - 通用工具函数
 */

// HTML 转义
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 格式化时间戳
function formatTime(ts) {
    if (!ts) return '-';
    return new Date(ts).toLocaleString('zh-CN');
}

// 格式化字节数
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 健康状态样式映射
function healthBadge(status) {
    if (status === 'green') return '<span class="badge bg-success">green</span>';
    if (status === 'yellow') return '<span class="badge bg-warning text-dark">yellow</span>';
    if (status === 'red') return '<span class="badge bg-danger">red</span>';
    return `<span class="badge bg-secondary">${status}</span>`;
}

// Toast 通知（简单实现）
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container') || (() => {
        const c = document.createElement('div');
        c.id = 'toast-container';
        c.className = 'toast-container position-fixed top-0 end-0 p-3';
        c.style.zIndex = '9999';
        document.body.appendChild(c);
        return c;
    })();

    const toast = document.createElement('div');
    toast.className = `toast show align-items-center text-bg-${type} border-0`;
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${escapeHtml(message)}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" onclick="this.closest('.toast').remove()"></button>
        </div>`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}
