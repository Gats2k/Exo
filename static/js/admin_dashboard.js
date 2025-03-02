function toggleDropdown() {
  const dropdown = document.getElementById('platformDropdown');
  dropdown.classList.toggle('show');
}

function selectPlatform(platform) {
    const selectedText = document.getElementById('selected-platform');
    const platformIcon = document.getElementById('platform-icon');
    const dropdown = document.getElementById('platformDropdown');
    const options = dropdown.getElementsByClassName('web-selector-option');

    // Update selected text and icon
    selectedText.textContent = platform.charAt(0).toUpperCase() + platform.slice(1);

    // Update icon based on platform
    switch(platform) {
        case 'web':
            platformIcon.className = 'bi bi-globe';
            break;
        case 'telegram':
            platformIcon.className = 'bi bi-telegram';
            break;
        case 'whatsapp':
            platformIcon.className = 'bi bi-whatsapp';
            break;
    }

    // Update active state
    Array.from(options).forEach(option => {
        option.classList.toggle('active', option.textContent.trim().toLowerCase() === platform);
    });

    // Hide dropdown
    dropdown.classList.remove('show');

    // Emit platform change event
    emitPlatformChange(platform);

    // Fetch initial data for the platform
    fetchPlatformData(platform);
}

function updateTableWithWebData(data) {
  const usersTable = document.getElementById('usersTable').getElementsByTagName('tbody')[0];
  const conversationsTable = document.getElementById('conversationsTable').getElementsByTagName('tbody')[0];

  // Clear existing table data
  usersTable.innerHTML = '';
  conversationsTable.innerHTML = '';

  // Update users table
  if (data.users && data.users.length > 0) {
      data.users.forEach(user => {
          const row = usersTable.insertRow();
          row.innerHTML = `
              <td>${user.last_name || ''}</td>
              <td>${user.first_name || ''}</td>
              <td>${user.age || ''}</td>
              <td>${user.phone_number || ''}</td>
              <td>${user.study_level || ''}</td>
              <td>${user.created_at || ''}</td>
          `;
      });
  }

  // Update conversations table
  if (data.conversations && data.conversations.length > 0) {
      data.conversations.forEach(conv => {
          // Formatage de la date si elle existe
          const formattedDate = conv.date ? new Date(conv.date).toLocaleDateString('fr-FR') : '';
          // Formatage de l'heure si elle existe
          const formattedTime = conv.time ? conv.time : '';
          // Tronquer le dernier message s'il est trop long
          const truncatedMessage = conv.last_message ? 
              (conv.last_message.length > 50 ? conv.last_message.substring(0, 50) + '...' : conv.last_message) : '';

          const row = conversationsTable.insertRow();
          row.innerHTML = `
              <td>${conv.title || 'Sans titre'}</td>
              <td>${formattedDate}</td>
              <td>${formattedTime}</td>
              <td>${truncatedMessage}</td>
          `;
      });
  }
}

function updateTableWithPlatformData(data) {
    const usersTable = document.getElementById('usersTable').getElementsByTagName('tbody')[0];
    const conversationsTable = document.getElementById('conversationsTable').getElementsByTagName('tbody')[0];

    // Clear existing table data
    usersTable.innerHTML = '';
    conversationsTable.innerHTML = '';

    // Update users table
    if (data.users && data.users.length > 0) {
        data.users.forEach(user => {
            const row = usersTable.insertRow();
            row.innerHTML = `
                <td>${user.name || ''}</td>
                <td>--</td>
                <td>--</td>
                <td>${user.phone || ''}</td>
                <td>${user.study_level || ''}</td>
                <td>${user.created_at || ''}</td>
            `;
        });
    }

    // Update conversations table
    if (data.conversations && data.conversations.length > 0) {
        data.conversations.forEach(conv => {
            const row = conversationsTable.insertRow();
            row.innerHTML = `
                <td>${conv.title || 'Sans titre'}</td>
                <td>${conv.date || ''}</td>
                <td>${conv.time || ''}</td>
                <td>${conv.last_message || ''}</td>
            `;
        });
    }
}

function updateDashboardStats(data) {
    try {
        // Update active users
        document.querySelector('.stat-value').textContent = data.active_users;
        document.querySelector('.stat-subtitle').textContent = `+${data.active_users_today} aujourd'hui`;

        // Update conversations
        document.querySelectorAll('.stat-value')[1].textContent = data.today_conversations;

        // Update satisfaction
        document.querySelectorAll('.stat-value')[2].textContent = `${data.satisfaction_rate}%`;

        // Get table and empty state elements
        const usersTable = document.getElementById('usersTable');
        const conversationsTable = document.getElementById('conversationsTable');
        const usersEmptyState = document.querySelector('#usersTableContainer .empty-state');
        const conversationsEmptyState = document.querySelector('#conversationsTableContainer .empty-state');

        // Update empty state messages based on platform
        if (data.platform === 'whatsapp') {
            usersEmptyState.querySelector('p').textContent = 'Aucun utilisateur WhatsApp disponible pour le moment';
            conversationsEmptyState.querySelector('p').textContent = 'Aucune conversation WhatsApp disponible pour le moment';
        } else if (data.platform === 'telegram') {
            usersEmptyState.querySelector('p').textContent = 'Aucun utilisateur Telegram disponible pour le moment';
            conversationsEmptyState.querySelector('p').textContent = 'Aucune conversation Telegram disponible pour le moment';
        }

        if (['telegram', 'whatsapp'].includes(data.platform)) {
            if (data.users && data.users.length > 0) {
                usersTable.style.display = 'table';
                usersEmptyState.style.display = 'none';
                updateTableWithPlatformData(data);
            } else {
                usersTable.style.display = 'none';
                usersEmptyState.style.display = 'block';
            }

            if (data.conversations && data.conversations.length > 0) {
                conversationsTable.style.display = 'table';
                conversationsEmptyState.style.display = 'none';
            } else {
                conversationsTable.style.display = 'none';
                conversationsEmptyState.style.display = 'block';
            }
        } else {
            // Handle Web data
            usersTable.style.display = 'table';
            conversationsTable.style.display = 'table';
            usersEmptyState.style.display = 'none';
            conversationsEmptyState.style.display = 'none';
            updateTableWithWebData(data);
        }
    } catch (error) {
        console.error('Error updating dashboard stats:', error);
    }
}

function fetchPlatformData(platform) {
  // Make an AJAX request to get platform-specific data
  fetch(`/admin/data/${platform}`)
      .then(response => {
          if (!response.ok) {
              throw new Error('Network response was not ok');
          }
          return response.json();
      })
      .then(data => {
          // Debugging logs - place them here after data is available
          console.log('Platform data received:', data);
          console.log('Conversations data:', data.conversations);

          // Add platform info to the data
          data.platform = platform;
          // Update the dashboard statistics with the new data
          updateDashboardStats(data);
      })
      .catch(error => {
          console.error('Error fetching platform data:', error);
          // Show empty states on error
          updateDashboardStats({
              platform: platform,
              active_users: 0,
              active_users_today: 0,
              today_conversations: 0,
              satisfaction_rate: 0
          });
      });
}

// Close dropdown when clicking outside
document.addEventListener('click', function(event) {
  const dropdown = document.getElementById('platformDropdown');
  const webSelector = document.querySelector('.web-selector');

  if (!webSelector.contains(event.target)) {
      dropdown.classList.remove('show');
  }
});

// Initialize socket connection
const socket = io();

// Listen for real-time updates
socket.on('stats_update', function(data) {
    console.log('Received stats update:', data);
    updateDashboardStats(data);
});

socket.on('connect', function() {
    console.log('Connected to server');
});

socket.on('disconnect', function() {
    console.log('Disconnected from server');
});

// Initialize the dashboard with web data by default
document.addEventListener('DOMContentLoaded', function() {
    fetchPlatformData('web');

    // Join the stats update room
    socket.emit('join_stats_room');
});

function emitPlatformChange(platform) {
    socket.emit('platform_changed', { platform: platform });
}