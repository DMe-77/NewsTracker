document.addEventListener('DOMContentLoaded', () => {
    loadData();
});

const { DateTime } = luxon;
let allIncidents = [];

async function loadData() {
    try {
        const response = await fetch('data.json');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();

        updateLastUpdated(data.last_updated);
        renderTrucksChart(data.truck_stats || []);
        allIncidents = data.incidents || [];
        setupIncidentControls();
        applyIncidentFilters();

    } catch (error) {
        console.error('Error loading data:', error);
        document.getElementById('incident-feed').innerHTML = '<p>Error loading data. Please try again later.</p>';
    }
}

function updateLastUpdated(timestamp) {
    const lastUpdated = DateTime.fromISO(timestamp).toFormat('dd.MM.yyyy HH:mm:ss');
    document.getElementById('last-updated').innerText = `Last Updated: ${lastUpdated}`;
    document.getElementById('footer-last-updated').innerText = lastUpdated;
}

function renderTrucksChart(truckStats) {
    const ctx = document.getElementById('trucks-chart').getContext('2d');

    const labels = truckStats.map(stat => DateTime.fromISO(stat.date).toFormat('dd.MM'));
    const kapitanAndreevoData = truckStats.map(stat => stat.checkpoints['Капитан Андреево']?.total || 0);
    const lesovoData = truckStats.map(stat => stat.checkpoints['Лесово']?.total || 0);
    const kalotinaData = truckStats.map(stat => stat.checkpoints['Калотина']?.total || 0);

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Капитан Андреево',
                    data: kapitanAndreevoData,
                    borderColor: '#ff4d4d',
                    backgroundColor: 'rgba(255, 77, 77, 0.1)',
                    fill: true,
                    tension: 0.3,
                },
                {
                    label: 'Лесово',
                    data: lesovoData,
                    borderColor: '#ffcc00',
                    backgroundColor: 'rgba(255, 204, 0, 0.1)',
                    fill: true,
                    tension: 0.3,
                },
                {
                    label: 'Калотина',
                    data: kalotinaData,
                    borderColor: '#00aaff',
                    backgroundColor: 'rgba(0, 170, 255, 0.1)',
                    fill: true,
                    tension: 0.3,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: false,
                    ticks: { color: '#e0e0e0' }
                },
                x: {
                    ticks: { color: '#e0e0e0' }
                }
            },
            plugins: {
                legend: {
                    labels: {
                         color: '#e0e0e0'
                    }
                }
            }
        }
    });
}

function setupIncidentControls() {
    const statusFilter = document.getElementById('status-filter');
    const searchFilter = document.getElementById('search-filter');
    statusFilter.addEventListener('change', applyIncidentFilters);
    searchFilter.addEventListener('input', applyIncidentFilters);
}

function applyIncidentFilters() {
    const statusValue = document.getElementById('status-filter').value;
    const searchValue = document.getElementById('search-filter').value.trim().toLowerCase();
    const filtered = allIncidents.filter((incident) => {
        const status = safeStatus(incident);
        const location = safeLocation(incident).toLowerCase();
        const headline = safeHeadline(incident).toLowerCase();
        const statusMatch = statusValue === 'all' || status === statusValue;
        const searchMatch = !searchValue || location.includes(searchValue) || headline.includes(searchValue);
        return statusMatch && searchMatch;
    });

    renderIncidentFeed(filtered);
}

function safeStatus(incident) {
    return (incident?.analysis?.status || '🚨 Статус: Информация').replace('🚨 Статус: ', '');
}

function safeLocation(incident) {
    return (incident?.analysis?.location || '📍 Локация: Не е посочена').replace('📍 Локация: ', '');
}

function safeHeadline(incident) {
    return (incident?.analysis?.headline || '📰 Няма заглавие').replace('📰 ', '');
}

function renderIncidentFeed(incidents) {
    const feed = document.getElementById('incident-feed');
    feed.innerHTML = ''; // Clear skeleton loaders

    if (!incidents || incidents.length === 0) {
        feed.innerHTML = '<p>No incidents match the current filter.</p>';
        return;
    }

    incidents.forEach(incident => {
        const card = document.createElement('div');
        const status = safeStatus(incident);
        card.className = `incident-card status-${status}`;

        const incidentDate = incident.first_seen_utc
            ? DateTime.fromISO(incident.first_seen_utc).toFormat('dd.MM.yyyy HH:mm')
            : 'n/a';

        const linksHtml = (incident.links || []).map(link =>
            `<a href="${link.url}" target="_blank">${link.domain}</a>`
        ).join(' ');

        card.innerHTML = `
            <div class="incident-header">
                <span class="location">📍 ${safeLocation(incident)}</span>
                <span class="status">${status}</span>
                <span class="date">📅 ${incidentDate}</span>
            </div>
            <div class="incident-body">
                <h3>${safeHeadline(incident)}</h3>
            </div>
            <div class="incident-links">
                ${linksHtml}
            </div>
        `;
        feed.appendChild(card);
    });
}
