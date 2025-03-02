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

  // Update platform icon
  if (platform === 'web') {
    platformIcon.className = 'bi bi-globe';
  } else if (platform === 'telegram') {
    platformIcon.className = 'bi bi-telegram';
  } else if (platform === 'whatsapp') {
    platformIcon.className = 'bi bi-whatsapp';
  }

  // Update active state
  Array.from(options).forEach(option => {
      option.classList.toggle('active', option.textContent.trim().toLowerCase() === platform);
  });

  // Hide dropdown
  dropdown.classList.remove('show');

  // Fetch data for selected platform
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
              <td>${user.phone_number || ''}</td>
              <td>${user.first_name} ${user.last_name}</td>
              <td>${user.age || ''}</td>
              <td>${user.study_level || ''}</td>
              <td>${user.created_at || ''}</td>
          `;
      });
  }

  // Update conversations table (unchanged)
  if (data.conversations && data.conversations.length > 0) {
      data.conversations.forEach(conv => {
          const formattedDate = conv.date ? new Date(conv.date).toLocaleDateString('fr-FR') : '';
          const formattedTime = conv.time ? conv.time : '';
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

function updateTableWithTelegramData(data) {
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
              <td>${user.phone || ''}</td>
              <td>${user.name || ''}</td>
              <td>--</td>
              <td>${user.study_level || ''}</td>
              <td>${user.created_at || ''}</td>
          `;
      });
  }

  // Update conversations table (unchanged)
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

function updateTableWithWhatsAppData(data) {
  const usersTable = document.getElementById('usersTable').getElementsByTagName('tbody')[0];
  const conversationsTable = document.getElementById('conversationsTable').getElementsByTagName('tbody')[0];
  const usersEmptyState = document.querySelector('#usersTableContainer .empty-state');
  const conversationsEmptyState = document.querySelector('#conversationsTableContainer .empty-state');

  // Show empty states
  usersTable.style.display = 'none';
  conversationsTable.style.display = 'none';
  usersEmptyState.style.display = 'block';
  conversationsEmptyState.style.display = 'block';

  // Update empty state messages
  usersEmptyState.innerHTML = `
    <i class="bi bi-whatsapp"></i>
    <p>Aucun utilisateur WhatsApp disponible pour le moment</p>
  `;
  conversationsEmptyState.innerHTML = `
    <i class="bi bi-chat-dots"></i>
    <p>Aucune conversation WhatsApp disponible pour le moment</p>
  `;
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

    if (data.platform === 'telegram') {
      // Handle Telegram data
      if (data.users && data.users.length > 0) {
        usersTable.style.display = 'table';
        usersEmptyState.style.display = 'none';
        updateTableWithTelegramData(data);
      } else {
        usersTable.style.display = 'none';
        usersEmptyState.style.display = 'block';
      }
    } else if (data.platform === 'whatsapp') {
      // Handle WhatsApp data (ensure all stats are zero)
      data.active_users = 0;
      data.active_users_today = 0;
      data.today_conversations = 0;
      data.satisfaction_rate = 0;

      // Update the display with zeros
      document.querySelector('.stat-value').textContent = '0';
      document.querySelector('.stat-subtitle').textContent = '+0 aujourd\'hui';
      document.querySelectorAll('.stat-value')[1].textContent = '0';
      document.querySelectorAll('.stat-value')[2].textContent = '0%';

      updateTableWithWhatsAppData(data);
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

// Initialize the dashboard with web data by default
document.addEventListener('DOMContentLoaded', function() {
  fetchPlatformData('web');
});