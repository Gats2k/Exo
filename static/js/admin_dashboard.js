let userIdToDelete = null;

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
    let visibleCount = 0;

    rows.forEach(row => {
        const status = row.querySelector('.status-badge').textContent.toLowerCase();

        if (filter === 'all' || 
            (filter === 'active' && status === 'actif') || 
            (filter === 'inactive' && status === 'inactif')) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });

    // Afficher/masquer le tableau et l'état vide en fonction des résultats
    const tableElement = document.getElementById('fullUsersTable');
    const container = document.getElementById('fullUsersTableContainer');
    const emptyState = container.querySelector('.empty-state');

    if (visibleCount === 0) {
        tableElement.style.display = 'none';
        emptyState.style.display = 'flex';

        // Adapter le message selon le filtre
        if (filter === 'active') {
            emptyState.querySelector('p').textContent = "Aucun utilisateur actif pour le moment";
        } else if (filter === 'inactive') {
            emptyState.querySelector('p').textContent = "Aucun utilisateur inactif pour le moment";
        } else {
            emptyState.querySelector('p').textContent = "Aucun utilisateur disponible pour le moment";
        }
    } else {
        tableElement.style.display = 'table';
        emptyState.style.display = 'none';
    }

    // Update filter button counts
    updateFilterCounts();
}

function updateFilterCounts() {
    const rows = document.querySelectorAll('#fullUsersTable tbody tr');
    let activeCount = 0;
    let inactiveCount = 0;

    rows.forEach(row => {
        const status = row.querySelector('.status-badge').textContent.toLowerCase();
        if (status === 'actif') {
            activeCount++;
        } else {
            inactiveCount++;
        }
    });

    // Update the filter buttons with counts
    document.querySelector('[data-filter="all"]').textContent = `Tous (${activeCount + inactiveCount})`;
    document.querySelector('[data-filter="active"]').textContent = `Actifs (${activeCount})`;
    document.querySelector('[data-filter="inactive"]').textContent = `Inactifs (${inactiveCount})`;
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
    currentPlatform = platform;
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
    console.log('Fetching users for platform:', platform);

    fetch(`/admin/data/${platform}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            console.log(`Data received for ${platform} users:`, data);

            if (data.users && data.users.length > 0) {
                const usersWithStatus = data.users.map(user => ({
                    ...user,
                    // Check last_active timestamp to determine if user is active
                    active: user.last_active ? 
                        (new Date(user.last_active) > new Date(Date.now() - 15 * 60 * 1000)) : false
                }));
                updateFullUsersTable(usersWithStatus, platform);
            } else {
                showEmptyState('fullUsersTableContainer', platform);
            }
        })
        .catch(error => {
            console.error(`Error fetching ${platform} users:`, error);
            showEmptyState('fullUsersTableContainer', platform);
        });
}

function updateFullUsersTable(users, platform) {
    const tableBody = document.getElementById('fullUsersTable').getElementsByTagName('tbody')[0];
    const tableElement = document.getElementById('fullUsersTable');
    const container = document.getElementById('fullUsersTableContainer');
    const emptyState = container.querySelector('.empty-state');

    // Debug pour voir les données reçues
    console.log(`Users data received for ${platform}:`, users);

    if (!users || users.length === 0) {
        tableElement.style.display = 'none';
        emptyState.style.display = 'flex';
        return;
    }

    tableElement.style.display = 'table';
    emptyState.style.display = 'none';
    tableBody.innerHTML = '';

    users.forEach(user => {
        const row = tableBody.insertRow();
        const isActive = user.active;

        // S'assurer que l'ID existe, sinon utiliser une alternative
        const userId = user.id || (user.phone_number || user.phone || user._id || '');

        // Ajouter l'ID comme attribut de données à la ligne
        row.setAttribute('data-user-id', userId);

        if (platform === 'web') {
            row.innerHTML = `
                <td>${user.last_name || ''}</td>
                <td>${user.first_name || ''}</td>
                <td>${user.age || '--'}</td>
                <td>${user.phone_number || ''}</td>
                <td>${user.study_level || ''}</td>
                <td>${user.created_at || ''}</td>
                <td><span class="status-badge ${isActive ? 'active' : 'inactive'}">${isActive ? 'Actif' : 'Inactif'}</span></td>
                <td class="action-buttons">
                    <button class="action-btn edit" onclick="editUser('${userId}')"><i class="bi bi-pencil"></i></button>
                    <button class="action-btn delete" onclick="deleteUser('${userId}')"><i class="bi bi-trash"></i></button>
                </td>
            `;
        } else {
            const name = platform === 'telegram' ? 
                (user.name || `Telegram User ${user.id || ''}`) : 
                (user.name || `WhatsApp User ${user.phone || 'None'}`);

            row.innerHTML = `
                <td>${name}</td>
                <td>--</td>
                <td>--</td>
                <td>${user.phone || '--'}</td>
                <td>${user.study_level || '--'}</td>
                <td>${user.created_at || ''}</td>
                <td><span class="status-badge ${isActive ? 'active' : 'inactive'}">${isActive ? 'Actif' : 'Inactif'}</span></td>
                <td class="action-buttons">
                    <button class="action-btn edit" onclick="editUser('${userId}')"><i class="bi bi-pencil"></i></button>
                    <button class="action-btn delete" onclick="deleteUser('${userId}')"><i class="bi bi-trash"></i></button>
                </td>
            `;
        }
    });

    // Update filter counts after populating the table
    updateFilterCounts();
}

function showEmptyState(containerId, platform) {
    const container = document.getElementById(containerId);
    const emptyState = container.querySelector('.empty-state');
    const table = container.querySelector('table');

    // Cacher le tableau et montrer l'état vide
    if (table) table.style.display = 'none';
    emptyState.style.display = 'flex';

    // Personnaliser le message selon la plateforme
    if (containerId === 'fullUsersTableContainer') {
        const platformName = platform === 'web' ? '' : platform.charAt(0).toUpperCase() + platform.slice(1);
        emptyState.querySelector('p').textContent = `Aucun utilisateur ${platformName} disponible pour le moment`;
    }
}


// Function to open the delete modal
function deleteUser(userId) {
    userIdToDelete = userId;
    const modal = document.getElementById('deleteModal');
    modal.style.display = 'block';

    // Prevent scrolling of the body
    document.body.style.overflow = 'hidden';
}

// Function to close the modal
function closeDeleteModal() {
    const modal = document.getElementById('deleteModal');
    modal.style.display = 'none';

    // Re-enable scrolling
    document.body.style.overflow = 'auto';

    // Reset the user ID
    userIdToDelete = null;
}

// Function to confirm and perform deletion
function confirmDeleteUser() {
    if (userIdToDelete === null) return;

    // Perform the delete request
    fetch(`/admin/users/${userIdToDelete}`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Error during deletion');
        }
        return response.json();
    })
    .then(data => {
        // Close the modal
        closeDeleteModal();

        // Refresh the users list
        fetchAllUsers(currentPlatform);
    })
    .catch(error => {
        console.error('Error:', error);
        // Handle error (you could display an error message)
        closeDeleteModal();
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

// Initialize the dashboard
document.addEventListener('DOMContentLoaded', function() {
    initializeNavigation();
    showSection('dashboard'); // Show dashboard by default
    fetchPlatformData('web');

    // Add event listeners for user filtering and search
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => filterUsers(btn.getAttribute('data-filter')));
    });

    // Écouteurs pour le modal de suppression
    document.querySelector('.close-modal').addEventListener('click', closeDeleteModal);
    document.getElementById('cancelDelete').addEventListener('click', closeDeleteModal);
    document.getElementById('confirmDelete').addEventListener('click', confirmDeleteUser);

    // Fermer le modal si on clique en dehors
    window.addEventListener('click', function(event) {
        const modal = document.getElementById('deleteModal');
        if (event.target === modal) {
            closeDeleteModal();
        }
    });

    document.getElementById('userSearchInput').addEventListener('input', searchUsers);
});