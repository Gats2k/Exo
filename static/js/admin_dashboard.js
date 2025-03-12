function showSection(sectionId) {
    // Hide all sections
    document.querySelectorAll('.section').forEach(section => {
        section.style.display = 'none';
    });

    // Show the selected section
    document.getElementById(sectionId + '-section').style.display = 'block';

    // Update active state in sidebar
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    document.querySelector(`[data-section="${sectionId}"]`).classList.add('active');
}

function initializeNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const section = item.getAttribute('data-section');
            showSection(section);
            if (section === 'users') {
                fetchAllUsers(currentPlatform);
            }
        });
    });
}

function filterUsers(filter) {
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelector(`[data-filter="${filter}"]`).classList.add('active');

    const rows = document.querySelectorAll('#fullUsersTable tbody tr');
    rows.forEach(row => {
        const status = row.querySelector('.status-badge').textContent.toLowerCase();
        if (filter === 'all' || status === filter) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

function searchUsers() {
    const searchTerm = document.getElementById('userSearchInput').value.toLowerCase();
    const rows = document.querySelectorAll('#fullUsersTable tbody tr');

    rows.forEach(row => {
        const text = Array.from(row.cells)
            .map(cell => cell.textContent.toLowerCase())
            .join(' ');

        if (text.includes(searchTerm)) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

let currentPlatform = 'web';

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

    // Fetch data for selected platform
    fetchPlatformData(platform);

    // Mettre à jour la section utilisateurs si elle est visible
    const usersSection = document.getElementById('users-section');
    if (usersSection.style.display === 'block') {
        loadFullUsersData();
    }

    // Update data based on current section
    const currentSection = document.querySelector('.section[style*="block"]').id.replace('-section', '');
    if (currentSection === 'users') {
        fetchAllUsers(platform);
    } else {
        fetchPlatformData(platform);
    }
}

function updateTableWithWebData(data) {
  const usersTable = document.getElementById('usersTable').getElementsByTagName('tbody')[0];
  const conversationsTable = document.getElementById('conversationsTable').getElementsByTagName('tbody')[0];

  // Clear existing table data
  usersTable.innerHTML = '';
  conversationsTable.innerHTML = '';

  // Update users table
  if (data.users && data.users.length > 0) {
      // Display only first 5 rows
      const displayUsers = data.users.slice(0, 5);
      displayUsers.forEach(user => {
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

      // Add "See more..." row if there are more than 5 users
        if (data.users.length >= 3) {
          const moreRow = usersTable.insertRow();
          moreRow.className = 'see-more-row';
          moreRow.innerHTML = `
              <td colspan="6" class="see-more-cell">See more...</td>
          `;
      }
  }

  // Update conversations table
  if (data.conversations && data.conversations.length > 0) {
      // Display only first 5 rows
      const displayConversations = data.conversations.slice(0, 5);
      displayConversations.forEach(conv => {
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

      // Add "See more..." row if there are more than 5 conversations
        if (data.conversations.length >= 3) {
          const moreRow = conversationsTable.insertRow();
          moreRow.className = 'see-more-row';
          moreRow.innerHTML = `
              <td colspan="4" class="see-more-cell">See more...</td>
          `;
      }
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
        // Display only first 5 rows
        const displayUsers = data.users.slice(0, 5);
        displayUsers.forEach(user => {
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

        // Add "See more..." row if there are more than 5 users
        if (data.users.length >= 3) {
            const moreRow = usersTable.insertRow();
            moreRow.className = 'see-more-row';
            moreRow.innerHTML = `
                <td colspan="6" class="see-more-cell">Voir plus...</td>
            `;
        }
    }

    // Update conversations table
    if (data.conversations && data.conversations.length > 0) {
        // Display only first 5 rows
        const displayConversations = data.conversations.slice(0, 5);
        displayConversations.forEach(conv => {
            const row = conversationsTable.insertRow();
            row.innerHTML = `
                <td>${conv.title || 'Sans titre'}</td>
                <td>${conv.date || ''}</td>
                <td>${conv.time || ''}</td>
                <td>${conv.last_message || ''}</td>
            `;
        });

        // Add "See more..." row if there are more than 5 conversations
        if (data.conversations.length >= 3) {
            const moreRow = conversationsTable.insertRow();
            moreRow.className = 'see-more-row';
            moreRow.innerHTML = `
                <td colspan="4" class="see-more-cell">Voir plus...</td>
            `;
        }
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
                // Cette ligne manquait - elle est nécessaire pour afficher les conversations
                updateTableWithPlatformData(data);
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

/* À AJOUTER */
// Fonction pour gérer les clics sur la sidebar
function handleNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const sections = document.querySelectorAll('.section');

    navItems.forEach(item => {
        item.addEventListener('click', function(e) {
            e.preventDefault();
            const targetSection = this.getAttribute('data-section');

            // Masquer toutes les sections
            sections.forEach(section => {
                section.style.display = 'none';
            });

            // Retirer la classe active de tous les items
            navItems.forEach(navItem => {
                navItem.classList.remove('active');
            });

            // Afficher la section ciblée
            document.getElementById(`${targetSection}-section`).style.display = 'block';
            this.classList.add('active');

            // Charger les données complètes si on est sur la section utilisateurs
            if (targetSection === 'users') {
                loadFullUsersData();
            }
        });
    });
}

// Fonction pour charger les données complètes des utilisateurs
function loadFullUsersData() {
    const platform = document.getElementById('selected-platform').textContent.toLowerCase();

    fetch(`/admin/data/${platform}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            updateFullUsersTable(data);
        })
        .catch(error => {
            console.error('Error fetching users data:', error);
            const fullUsersTable = document.getElementById('fullUsersTable');
            const emptyState = document.querySelector('#fullUsersTableContainer .empty-state');

            fullUsersTable.style.display = 'none';
            emptyState.style.display = 'block';
        });
}

// Fonction pour mettre à jour le tableau complet des utilisateurs
function updateFullUsersTable(data) {
    const fullUsersTable = document.getElementById('fullUsersTable').getElementsByTagName('tbody')[0];
    const emptyState = document.querySelector('#fullUsersTableContainer .empty-state');

    // Vider le tableau existant
    fullUsersTable.innerHTML = '';

    if (data.users && data.users.length > 0) {
        data.users.forEach(user => {
            const row = fullUsersTable.insertRow();

            // Différencier l'affichage selon la plateforme
            if (data.platform === 'web') {
                row.innerHTML = `
                    <td>${user.last_name || ''}</td>
                    <td>${user.first_name || ''}</td>
                    <td>${user.age || ''}</td>
                    <td>${user.phone_number || ''}</td>
                    <td>${user.study_level || ''}</td>
                    <td>${user.created_at || ''}</td>
                    <td><span class="status-badge ${user.active ? 'active' : 'inactive'}">${user.active ? 'Actif' : 'Inactif'}</span></td>
                    <td>
                        <button class="action-btn view-btn"><i class="bi bi-eye"></i></button>
                        <button class="action-btn edit-btn"><i class="bi bi-pencil"></i></button>
                    </td>
                `;
            } else {
                row.innerHTML = `
                    <td>${user.name || ''}</td>
                    <td>--</td>
                    <td>--</td>
                    <td>${user.phone || ''}</td>
                    <td>${user.study_level || ''}</td>
                    <td>${user.created_at || ''}</td>
                    <td><span class="status-badge ${user.active ? 'active' : 'inactive'}">${user.active ? 'Actif' : 'Inactif'}</span></td>
                    <td>
                        <button class="action-btn view-btn"><i class="bi bi-eye"></i></button>
                        <button class="action-btn edit-btn"><i class="bi bi-pencil"></i></button>
                    </td>
                `;
            }
        });

        fullUsersTable.style.display = 'table';
        emptyState.style.display = 'none';
    } else {
        fullUsersTable.style.display = 'none';
        emptyState.style.display = 'block';
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

function fetchAllUsers(platform) {
    fetch(`/admin/users/${platform}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            updateFullUsersTable(data.users);
        })
        .catch(error => {
            console.error('Error fetching users:', error);
            showEmptyState('fullUsersTableContainer', platform);
        });
}

function updateFullUsersTable(users) {
    const table = document.getElementById('fullUsersTable').getElementsByTagName('tbody')[0];
    const container = document.getElementById('fullUsersTableContainer');
    const emptyState = container.querySelector('.empty-state');

    if (!users || users.length === 0) {
        table.style.display = 'none';
        emptyState.style.display = 'block';
        return;
    }

    table.style.display = 'table';
    emptyState.style.display = 'none';
    table.innerHTML = '';

    users.forEach(user => {
        const row = table.insertRow();
        row.innerHTML = `
            <td>${user.last_name || user.name || ''}</td>
            <td>${user.first_name || ''}</td>
            <td>${user.age || '--'}</td>
            <td>${user.phone_number || user.phone || ''}</td>
            <td>${user.study_level || ''}</td>
            <td>${user.created_at || ''}</td>
            <td><span class="status-badge ${user.active ? 'active' : 'inactive'}">${user.active ? 'Actif' : 'Inactif'}</span></td>
            <td class="action-buttons">
                <button class="action-btn edit" onclick="editUser(${user.id})"><i class="bi bi-pencil"></i></button>
                <button class="action-btn delete" onclick="deleteUser(${user.id})"><i class="bi bi-trash"></i></button>
            </td>
        `;
    });
}


function showEmptyState(containerId, platform) {
    const container = document.getElementById(containerId);
    const emptyState = container.querySelector('.empty-state');
    emptyState.style.display = 'block';
    //Customize empty state message based on platform and container
    if (containerId === 'fullUsersTableContainer') {
        emptyState.querySelector('p').textContent = `Aucun utilisateur ${platform === 'web' ? '' : platform.charAt(0).toUpperCase() + platform.slice(1)} disponible pour le moment`;
    }

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
  initializeNavigation();
  showSection('dashboard'); // Show dashboard by default
  fetchPlatformData('web');
  handleNavigation();

  // Add event listeners for user filtering and search
  document.querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => filterUsers(btn.getAttribute('data-filter')));
  });

  document.getElementById('userSearchInput').addEventListener('input', searchUsers);
});