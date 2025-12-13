// Initialize Map
// Base Layers
const osmLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
});

const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
});

// Initialize Map
const map = L.map('map', {
    center: [35.6895, 139.6917],
    zoom: 10,
    layers: [satelliteLayer] // Default layer
});

// Photo Icon
const photoIcon = L.divIcon({
    className: 'photo-marker-icon',
    html: '📷',
    iconSize: [24, 24],
    iconAnchor: [12, 12]
});

// Layer Control
const baseMaps = {
    "Dark Mode": osmLayer,
    "Satellite": satelliteLayer
};

L.control.layers(baseMaps).addTo(map);

let hikesData = [];
let activeLayer = null;

const hikeLayers = new Map(); // Store references to layers by hike index
let elevationChart = null;
let elevationMarker = null;

let photoMarkers = L.layerGroup(); // Store photo markers
let startEndMarkers = L.layerGroup(); // Store start/end markers
let coloredTrackLayer = null; // Store the gradient track
let activePhotoMarkers = new Map(); // Map url -> marker layer

// UI Elements
const detailsPanel = document.getElementById('details-panel');
const sidebarContainer = document.getElementById('left-sidebar-container');
const closeBtn = document.getElementById('close-details');

if (closeBtn) {
    closeBtn.addEventListener('click', (e) => {
        e.stopPropagation(); // Prevent map click if needed
        closeDetails();
    });
}

// Mobile Controls (Toggle + Maps)
let mapsBtn = null; // Global ref to update link

function initMobileControls() {
    const container = document.createElement('div');
    container.className = 'mobile-controls';

    // 1. Toggle Button
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'mobile-control-btn';

    const arrowDown = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>`;
    const arrowUp = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"></polyline></svg>`;

    toggleBtn.innerHTML = arrowDown;

    toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        sidebarContainer.classList.toggle('minimized');
        toggleBtn.innerHTML = sidebarContainer.classList.contains('minimized') ? arrowUp : arrowDown;
    });

    // 2. Maps Button (Hidden by default)
    mapsBtn = document.createElement('button');
    mapsBtn.className = 'mobile-control-btn maps-btn hidden'; // reusing style class
    // Map Icon
    mapsBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"></polygon><line x1="8" y1="2" x2="8" y2="18"></line><line x1="16" y1="6" x2="16" y2="22"></line></svg>`;

    container.appendChild(toggleBtn);
    container.appendChild(mapsBtn);

    sidebarContainer.prepend(container);
}

// Init on load
document.addEventListener('DOMContentLoaded', () => {
    initMobileControls();
});

function closeDetails() {
    detailsPanel.classList.add('hidden');
    sidebarContainer.classList.remove('details-open');
    if (activeLayer) {
        activeLayer.setStyle({ weight: 6, opacity: 0.9, color: '#38bdf8' });
        activeLayer = null;
    }
    if (elevationMarker) {
        map.removeLayer(elevationMarker);
        elevationMarker = null;
    }
    photoMarkers.clearLayers(); // Clear photos when closing
    startEndMarkers.clearLayers(); // Clear start/end markers

    // Clear Gradient Track
    if (coloredTrackLayer) {
        map.removeLayer(coloredTrackLayer);
        coloredTrackLayer = null;
    }

    // Reset URL
    const url = new URL(window.location);
    url.searchParams.delete('hike');
    window.history.pushState({}, '', url);

    // Hide Maps Button
    if (mapsBtn) {
        mapsBtn.classList.add('hidden');
    }
}

async function loadHikes() {
    try {
        const response = await fetch('data/hikes.json');
        hikesData = await response.json();

        // Sort by date descending (latest first)
        hikesData.sort((a, b) => new Date(b.date) - new Date(a.date));

        updateStats();
        renderHikesList();
        renderAllHikes();

        // Check for URL params
        checkUrlParams();
    } catch (error) {
        console.error("Error loading hikes:", error);
    }
}

function updateStats() {
    const totalDistance = hikesData.reduce((acc, hike) => acc + hike.length_2d, 0) / 1000; // km
    const totalElevation = hikesData.reduce((acc, hike) => acc + hike.uphill, 0); // m

    const statsContainer = document.getElementById('stats-summary');
    statsContainer.innerHTML = `
        <div class="stat-card">
            <span class="stat-value">${hikesData.length}</span>
            <span class="stat-label">Hikes</span>
        </div>
        <div class="stat-card">
            <span class="stat-value">${totalDistance.toFixed(1)} km</span>
            <span class="stat-label">Total Dist</span>
        </div>
        <div class="stat-card">
            <span class="stat-value">${totalElevation.toFixed(0)} m</span>
            <span class="stat-label">Elevation Gain</span>
        </div>
        <div class="stat-card">
            <span class="stat-value">${(totalDistance / hikesData.length).toFixed(1)} km</span>
            <span class="stat-label">Avg Dist</span>
        </div>
    `;
}

function renderHikesList() {
    const listContainer = document.getElementById('hikes-list');
    listContainer.innerHTML = '';

    hikesData.forEach((hike, index) => {
        const item = document.createElement('div');
        item.className = 'hike-item';
        item.onclick = () => focusHike(index);

        const date = hike.date ? new Date(hike.date).toLocaleDateString('en-GB') : 'Unknown Date';
        const distance = (hike.length_2d / 1000).toFixed(1);

        const photoHtml = hike.thumbnail
            ? `<div class="hike-thumbnail" style="background-image: url('${hike.thumbnail}')"></div>`
            : '';

        item.innerHTML = `
            ${photoHtml}
            <div class="hike-info">
                <h3>${hike.name}</h3>
                <div class="hike-meta">
                    <span>${date}</span>
                    <span>${distance} km</span>
                </div>
            </div>
        `;

        listContainer.appendChild(item);
    });
}

function renderAllHikes() {
    const bounds = L.latLngBounds([]);

    hikesData.forEach((hike, index) => {
        // Points in GPX are [lat, lon, ele]
        // Leaflet expects [lat, lon]
        const latLngs = hike.points.map(p => [p[0], p[1]]);

        const polyline = L.polyline(latLngs, {
            color: '#38bdf8',
            weight: 6,
            opacity: 0.9
        }).addTo(map);

        polyline.on('click', () => focusHike(index));
        polyline.on('mouseover', () => {
            polyline.setStyle({ weight: 8, opacity: 1, color: '#0ea5e9' });
        });
        polyline.on('mouseout', () => {
            if (activeLayer !== polyline) {
                polyline.setStyle({ weight: 6, opacity: 0.9, color: '#38bdf8' });
            }
        });

        hikeLayers.set(index, polyline);
        bounds.extend(latLngs);
    });

    if (hikesData.length > 0) {
        map.fitBounds(bounds, { padding: [50, 50] });
    }
}

function focusHike(index) {
    const hike = hikesData[index];
    const layer = hikeLayers.get(index);

    // Reset previous active layer style
    if (activeLayer && activeLayer !== layer) {
        activeLayer.setStyle({ weight: 6, opacity: 0.9, color: '#38bdf8' });
    }

    // Highlight new layer (Make it invisible since we draw the gradient on top)
    // Actually, keep it visible but thinner/transparent as a "glow" or base?
    // Or just Hide it.
    // layer.setStyle({ weight: 5, opacity: 1, color: '#f43f5e' }); 
    layer.setStyle({ opacity: 0 }); // Hide base layer while active
    layer.bringToFront();
    activeLayer = layer;

    // Draw Gradient Track
    if (coloredTrackLayer) {
        map.removeLayer(coloredTrackLayer);
    }
    coloredTrackLayer = drawElevationTrack(hike);
    coloredTrackLayer.addTo(map);

    // Draw Start/End Markers
    startEndMarkers.clearLayers();
    if (hike.points.length > 0) {
        const start = hike.points[0];
        const end = hike.points[hike.points.length - 1];

        // Start Dot (Green)
        L.circleMarker([start[0], start[1]], {
            radius: 8,
            fillColor: '#22c55e', // Green
            color: '#ffffff',
            weight: 2,
            opacity: 1,
            fillOpacity: 1
        }).addTo(startEndMarkers).bindTooltip("Start", { direction: 'top', offset: [0, -10] });

        // End Dot (Red)
        L.circleMarker([end[0], end[1]], {
            radius: 8,
            fillColor: '#ef4444', // Red
            color: '#ffffff',
            weight: 2,
            opacity: 1,
            fillOpacity: 1
        }).addTo(startEndMarkers).bindTooltip("End", { direction: 'top', offset: [0, -10] });

        // Peak Marker (Highest Point)
        if (hike.points.length > 0) {
            const maxPoint = hike.points.reduce((prev, curr) => (prev[2] > curr[2]) ? prev : curr);

            L.marker([maxPoint[0], maxPoint[1]], {
                icon: L.divIcon({
                    className: 'peak-marker-icon', // Reuse or similar to photo-marker
                    html: '<div style="font-size: 24px; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));">⛰️</div>',
                    iconSize: [30, 30],
                    iconAnchor: [15, 15]
                })
            }).addTo(startEndMarkers).bindTooltip(`Peak: ${Math.round(maxPoint[2])}m`, { direction: 'top', offset: [0, -15] });
        }

        startEndMarkers.addTo(map);
    }

    // Zoom to hike
    map.fitBounds(layer.getBounds(), { padding: [50, 50] });

    // Highlight in list
    document.querySelectorAll('.hike-item').forEach((el, i) => {
        if (i === index) el.classList.add('active');
        else el.classList.remove('active');
    });

    // Scroll list to item
    const listItem = document.querySelectorAll('.hike-item')[index];
    if (listItem) {
        listItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    // Update URL
    const url = new URL(window.location);
    url.searchParams.set('hike', hike.name);
    window.history.pushState({}, '', url);

    // Show Details Panel
    renderDetails(hike);
}

function renderDetails(hike) {
    sidebarContainer.classList.add('details-open');
    detailsPanel.classList.remove('hidden');
    document.getElementById('detail-title').innerHTML = `
        ${hike.name} 
        <a href="https://www.google.com/maps/search/?api=1&query=${hike.points[0][0]},${hike.points[0][1]}" 
           target="_blank" 
           class="desktop-maps-link" 
           title="Open in Google Maps">
           <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"></polygon><line x1="8" y1="2" x2="8" y2="18"></line><line x1="16" y1="6" x2="16" y2="22"></line></svg>
        </a>
    `;

    // Show Google Maps button logic (existing)...
    if (mapsBtn && hike.points.length > 0) {
        const start = hike.points[0];
        mapsBtn.classList.remove('hidden');
        mapsBtn.onclick = (e) => {
            e.stopPropagation();
            const url = `https://www.google.com/maps/search/?api=1&query=${start[0]},${start[1]}`;
            window.open(url, '_blank');
        };
    }

    // Render Album
    const albumContainer = document.getElementById('album-container');
    albumContainer.innerHTML = ''; // Clear previous
    if (hike.photos && hike.photos.length > 0) {
        albumContainer.style.display = 'flex';
        hike.photos.forEach(photo => {
            const img = document.createElement('img');
            img.src = photo.url;
            img.className = 'album-photo';
            img.loading = 'lazy';
            img.onclick = (e) => {
                e.stopPropagation();
                // Find and activate marker
                const marker = activePhotoMarkers.get(photo.url);
                if (marker) {
                    // Pan to marker
                    map.flyTo(marker.getLatLng(), 15); // Adjust zoom if needed
                    marker.openPopup();
                } else {
                    // Fallback just in case
                    window.open(photo.url, '_blank');
                }
            };
            albumContainer.appendChild(img);
        });
    } else {
        albumContainer.style.display = 'none';
    }

    // Stats in details
    const distance = (hike.length_2d / 1000).toFixed(2);
    const elevation = hike.uphill.toFixed(0);
    const date = hike.date ? new Date(hike.date).toLocaleDateString('en-GB') : 'Unknown';
    const duration = (hike.duration / 3600).toFixed(1);

    const statsContainer = document.getElementById('detail-stats');
    statsContainer.innerHTML = `
        <div class="stat-card">
            <span class="stat-value">${distance} km</span>
            <span class="stat-label">Distance</span>
        </div>
        <div class="stat-card">
            <span class="stat-value">${elevation} m</span>
            <span class="stat-label">Elevation</span>
        </div>
        <div class="stat-card">
            <span class="stat-value">${duration} h</span>
            <span class="stat-label">Total Time</span>
        </div>
        <div class="stat-card">
            <span class="stat-value">${date}</span>
            <span class="stat-label">Date</span>
        </div>
    `;

    renderChart(hike);
    renderPhotoMarkers(hike);
}

function renderPhotoMarkers(hike) {
    photoMarkers.clearLayers();
    activePhotoMarkers.clear();

    if (hike.photos) {
        // Collect critical points to avoid (Start, End, Peak)
        const obstacles = [];
        startEndMarkers.eachLayer(layer => {
            obstacles.push(layer.getLatLng());
        });

        hike.photos.forEach(photo => {
            let lat = photo.lat;
            let lon = photo.lon;
            const originalLatLng = L.latLng(lat, lon);

            // Simple Collision Detection / Nudging
            let isOverlapping = false;
            for (const obstacle of obstacles) {
                // If closer than 50 meters, consider it overlapping
                if (map.distance(originalLatLng, obstacle) < 50) {
                    isOverlapping = true;
                    break;
                }
            }

            // If overlapping, nudge the photo slightly (random angle)
            if (isOverlapping) {
                // ~0.0005 degrees is roughly 50m
                const angle = Math.random() * 2 * Math.PI;
                const offset = 0.0004;
                lat += Math.cos(angle) * offset;
                lon += Math.sin(angle) * offset;

                // Add a dashed line to original location? (Visual polish, optional)
                L.polyline([originalLatLng, [lat, lon]], {
                    color: '#ffffff',
                    weight: 1,
                    dashArray: '4, 4',
                    opacity: 0.8
                }).addTo(photoMarkers);
            }

            const marker = L.marker([lat, lon], { icon: photoIcon });
            marker.bindPopup(`<img src="${photo.url}" style="max-width: 200px; border-radius: 8px;">`);
            photoMarkers.addLayer(marker);
            activePhotoMarkers.set(photo.url, marker);
        });
        photoMarkers.addTo(map);
    }
}

function renderChart(hike) {
    const ctx = document.getElementById('elevation-chart').getContext('2d');

    // Calculate distance for X axis
    // Points are [lat, lon, ele]
    const elevationData = hike.points.map(p => p[2]);
    const labels = elevationData.map((_, i) => i); // Simple index for now, could actally calculate accumulated distance

    if (elevationChart) {
        elevationChart.destroy();
    }

    // Create gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, 250);
    gradient.addColorStop(0, 'rgba(56, 189, 248, 0.5)');
    gradient.addColorStop(1, 'rgba(56, 189, 248, 0.0)');

    elevationChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Elevation (m)',
                data: elevationData,
                borderColor: '#38bdf8',
                backgroundColor: gradient,
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 4,
                fill: true,
                tension: 0.2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },

            // Interaction logic
            onHover: (event, elements) => {
                if (elements && elements.length > 0) {
                    const index = elements[0].index;
                    const point = hike.points[index]; // [lat, lon, ele]

                    if (point) {
                        const latLng = [point[0], point[1]];

                        if (!elevationMarker) {
                            elevationMarker = L.circleMarker(latLng, {
                                radius: 8,
                                fillColor: '#f43f5e',
                                color: '#fff',
                                weight: 2,
                                opacity: 1,
                                fillOpacity: 0.8
                            }).addTo(map);
                        } else {
                            elevationMarker.setLatLng(latLng);
                        }
                    }
                } else {
                    // Remove marker if hovering away (optional, maybe distracting)
                    // if (elevationMarker) {
                    //    map.removeLayer(elevationMarker);
                    //    elevationMarker = null;
                    // }
                }
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    displayColors: false,
                    callbacks: {
                        label: function (context) {
                            return context.parsed.y.toFixed(0) + ' m';
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: false, // Hide x axis for cleaner look
                },
                y: {
                    grid: {
                        color: 'rgba(255, 255, 255, 0.1)'
                    },
                    ticks: {
                        color: '#94a3b8'
                    }
                }
            }
        }
    });
}



// --- COLOR CODED TRACK FEATURE ---
// Calculate Slope Gradient (Steepness) with Direction
// Red = Steep Up, Green = Flat, Blue = Steep Down
function drawElevationTrack(hike) {
    const segments = [];

    for (let i = 0; i < hike.points.length - 1; i++) {
        const p1 = hike.points[i];
        const p2 = hike.points[i + 1];

        const dist = map.distance([p1[0], p1[1]], [p2[0], p2[1]]);
        const eleDiff = p2[2] - p1[2]; // Signed difference

        let slope = 0;
        if (dist > 0) {
            slope = (eleDiff / dist) * 100; // Percent slope
        }

        // Clamp slope to +/- 30%
        const maxSlope = 30;
        let color;

        if (slope >= 0) {
            // UPHILL: Green (0%) -> Red (30%)
            const intensity = Math.min(slope / maxSlope, 1.0);

            // Mix Green (0, 255, 0) to Red (255, 0, 0)
            // Midpoint Yellow (255, 255, 0)
            if (intensity < 0.5) {
                // Green to Yellow
                const r = Math.floor(255 * (intensity * 2));
                const g = 255;
                const b = 0;
                color = `rgb(${r},${g},${b})`;
            } else {
                // Yellow to Red
                const r = 255;
                const g = Math.floor(255 * (2 - intensity * 2));
                const b = 0;
                color = `rgb(${r},${g},${b})`;
            }
        } else {
            // DOWNHILL: Green (0%) -> Blue (30%)
            const intensity = Math.min(Math.abs(slope) / maxSlope, 1.0);

            // Mix Green (0, 255, 0) to Blue (0, 0, 255)
            // Midpoint Cyan (0, 255, 255)
            if (intensity < 0.5) {
                // Green to Cyan
                const r = 0;
                const g = 255;
                const b = Math.floor(255 * (intensity * 2));
                color = `rgb(${r},${g},${b})`;
            } else {
                // Cyan to Blue
                const r = 0;
                const g = Math.floor(255 * (2 - intensity * 2));
                const b = 255;
                color = `rgb(${r},${g},${b})`;
            }
        }

        segments.push(L.polyline([[p1[0], p1[1]], [p2[0], p2[1]]], {
            color: color,
            weight: 5,
            opacity: 1,
            interactive: false
        }));
    }

    return L.layerGroup(segments);
}

function checkUrlParams() {
    const urlParams = new URLSearchParams(window.location.search);
    const hikeName = urlParams.get('hike');

    if (hikeName) {
        const index = hikesData.findIndex(h => h.name === hikeName);
        if (index !== -1) {
            focusHike(index);
        }
    }
}

loadHikes();
