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

    // Fetch appropriate data based on section
    if (sectionId === 'users') {
        fetchAllUsers(currentPlatform);
    } else if (sectionId === 'conversations') {
        fetchAllConversations(currentPlatform);
    }
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
    } else if (currentSection === 'conversations') {
        fetchAllConversations(platform);
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

        // Déterminer l'ID correct selon la plateforme
        let userId;

        if (platform === 'web') {
            // Pour le web, utiliser phone_number comme ID
            userId = user.phone_number || '';
        } else if (platform === 'telegram') {
            // Pour Telegram, extraire telegram_id du nom qui est au format "Telegram User {id}"
            const match = user.name && user.name.match(/Telegram User (\d+)/);
            userId = match ? match[1] : (user.phone || '');
        } else {
            // Pour WhatsApp, utiliser le numéro de téléphone
            userId = user.phone || '';
        }

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
                (user.name || `Telegram User ${userId || ''}`) : 
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

function showEmptyState(containerId, platform, type = 'users') {
    const container = document.getElementById(containerId);
    const emptyState = container.querySelector('.empty-state');
    const table = container.querySelector('table');

    // Cacher le tableau et montrer l'état vide
    if (table) table.style.display = 'none';
    emptyState.style.display = 'flex';

    // Personnaliser le message selon la plateforme et le type
    if (containerId === 'fullUsersTableContainer') {
        const platformName = platform === 'web' ? '' : platform.charAt(0).toUpperCase() + platform.slice(1);
        emptyState.querySelector('p').textContent = `Aucun utilisateur ${platformName} disponible pour le moment`;
    } else if (containerId === 'fullConversationsTableContainer') {
        const platformName = platform === 'web' ? '' : platform.charAt(0).toUpperCase() + platform.slice(1);
        emptyState.querySelector('p').textContent = `Aucune conversation ${platformName} disponible pour le moment`;
    }
}

let userIdToDelete = null;

// Fonction pour ouvrir le modal de suppression
function deleteUser(userId) {
    userIdToDelete = userId;
    const modal = document.getElementById('deleteModal');
    modal.style.display = 'block';

    // Empêcher le défilement du corps de la page
    document.body.style.overflow = 'hidden';
}

// Fonction pour fermer le modal
function closeDeleteModal() {
    const modal = document.getElementById('deleteModal');
    modal.style.display = 'none';

    // Réactiver le défilement
    document.body.style.overflow = 'auto';

    // Réinitialiser l'ID utilisateur
    userIdToDelete = null;
}

// Fonction pour confirmer et effectuer la suppression
function confirmDeleteUser() {
    if (userIdToDelete === null) return;

    // Effectuer la requête de suppression
    fetch(`/admin/users/${userIdToDelete}`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Erreur lors de la suppression');
        }
        return response.json();
    })
    .then(data => {
        // Suppression réussie, fermer le modal
        closeDeleteModal();

        // Rafraîchir la liste des utilisateurs
        fetchAllUsers(currentPlatform);
    })
    .catch(error => {
        console.error('Erreur:', error);
        // Gérer l'erreur (vous pourriez afficher un message d'erreur)
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


// Add these functions after the existing user-related functions

let conversationIdToDelete = null;

function fetchAllConversations(platform) {
    console.log('Fetching conversations for platform:', platform);

    fetch(`/admin/data/${platform}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            console.log(`Data received for ${platform} conversations:`, data);
            updateFullConversationsTable(data.conversations || [], platform);
        })
        .catch(error => {
            console.error(`Error fetching ${platform} conversations:`, error);
            showEmptyState('fullConversationsTableContainer', platform, 'conversations');
        });
}


function updateFullConversationsTable(conversations, platform) {
    const tableBody = document.getElementById('fullConversationsTable').getElementsByTagName('tbody')[0];
    const tableElement = document.getElementById('fullConversationsTable');
    const container = document.getElementById('fullConversationsTableContainer');
    const emptyState = container.querySelector('.empty-state');

    console.log(`Updating conversations table for ${platform}:`, conversations); // Debug log

    if (!conversations || conversations.length === 0) {
        tableElement.style.display = 'none';
        emptyState.style.display = 'flex';
        return;
    }

    tableElement.style.display = 'table';
    emptyState.style.display = 'none';
    tableBody.innerHTML = '';

    conversations.forEach(conversation => {
        const row = tableBody.insertRow();
        const isActive = conversation.status === 'active';
        const truncatedMessage = conversation.last_message ? 
            (conversation.last_message.length > 50 ? conversation.last_message.substring(0, 50) + '...' : conversation.last_message) : 
            'Pas de message';

        // Get the conversation ID based on the platform
        const conversationId = platform === 'whatsapp' ? 
            conversation.thread_id : conversation.id;

        console.log('Processing conversation:', { id: conversationId, platform }); // Debug log

        // Create the row content
        row.innerHTML = `
            <td>${conversation.title || 'Sans titre'}</td>
            <td><span class="platform-badge ${platform}">${platform}</span></td>
            <td>${conversation.date || ''}</td>
            <td>${truncatedMessage}</td>
            <td><span class="status-badge ${isActive ? 'active' : 'archived'}">${isActive ? 'Active' : 'Archivée'}</span></td>
            <td class="action-buttons">
                <button class="action-btn view">
                    <i class="bi bi-eye"></i>
                </button>
                <button class="action-btn delete">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        `;

        // Add click event listeners
        const viewBtn = row.querySelector('.action-btn.view');
        const deleteBtn = row.querySelector('.action-btn.delete');

        viewBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('View button clicked for conversation:', conversationId);
            viewConversation(conversationId);
        });

        deleteBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Delete button clicked for conversation:', conversationId);
            deleteConversation(conversationId);
        });
    });

    updateConversationFilterCounts();
}

function filterConversations(filter) {
    document.querySelectorAll('.conversations-filters .filter-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelector(`.conversations-filters [data-filter="${filter}"]`).classList.add('active');

    const rows = document.querySelectorAll('#fullConversationsTable tbody tr');
    let visibleCount = 0;

    rows.forEach(row => {
        const status = row.querySelector('.status-badge').textContent.toLowerCase();

        if (filter === 'all' || 
            (filter === 'active' && status === 'active') || 
            (filter === 'archived' && status === 'archivée')) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });

    const tableElement = document.getElementById('fullConversationsTable');
    const container = document.getElementById('fullConversationsTableContainer');
    const emptyState = container.querySelector('.empty-state');

    if (visibleCount === 0) {
        tableElement.style.display = 'none';
        emptyState.style.display = 'flex';
        emptyState.querySelector('p').textContent = `Aucune conversation ${filter === 'active' ? 'active' : filter === 'archived' ? 'archivée' : ''} disponible`;
    } else {
        tableElement.style.display = 'table';
        emptyState.style.display = 'none';
    }
}

function updateConversationFilterCounts() {
    const rows = document.querySelectorAll('#fullConversationsTable tbody tr');
    let activeCount = 0;
    let archivedCount = 0;

    rows.forEach(row => {
        const status = row.querySelector('.status-badge').textContent.toLowerCase();
        if (status === 'active') {
            activeCount++;
        } else {
            archivedCount++;
        }
    });

    document.querySelector('.conversations-filters [data-filter="all"]').textContent = `Toutes (${activeCount + archivedCount})`;
    document.querySelector('.conversations-filters [data-filter="active"]').textContent = `Actives (${activeCount})`;
    document.querySelector('.conversations-filters [data-filter="archived"]').textContent = `Archivées (${archivedCount})`;
}

function searchConversations() {
    const searchTerm = document.getElementById('conversationSearchInput').value.toLowerCase();
    const rows = document.querySelectorAll('#fullConversationsTable tbody tr');
    let visibleCount = 0;

    rows.forEach(row => {
        const text = Array.from(row.cells)
            .map(cell => cell.textContent.toLowerCase())
            .join(' ');

        if (text.includes(searchTerm)) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });

    const tableElement = document.getElementById('fullConversationsTable');
    const container = document.getElementById('fullConversationsTableContainer');
    const emptyState = container.querySelector('.empty-state');

    if (visibleCount === 0) {
        tableElement.style.display = 'none';
        emptyState.style.display = 'flex';
        emptyState.querySelector('p').textContent = "Aucune conversation ne correspond à votre recherche";
    } else {
        tableElement.style.display = 'table';
        emptyState.style.display = 'none';
    }
}

function deleteConversation(conversationId) {
    conversationIdToDelete = conversationId;
    const modal = document.getElementById('deleteConversationModal');
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';
}

function closeDeleteConversationModal() {
    const modal = document.getElementById('deleteConversationModal');
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
    conversationIdToDelete = null;
}

function confirmDeleteConversation() {
    if (conversationIdToDelete === null) return;

    fetch(`/admin/conversations/${conversationIdToDelete}`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Erreur lors de la suppression');
        }
        return response.json();
    })
    .then(data => {
        closeDeleteConversationModal();
        fetchAllConversations(currentPlatform);
    })
    .catch(error => {
        console.error('Erreur:', error);
        closeDeleteConversationModal();
    });
}

function viewConversation(conversationId) {
    if (!conversationId) {
        console.error('Invalid conversation ID:', conversationId);
        return;
    }

    console.log('Opening conversation modal for ID:', conversationId);

    // Open the modal and show loading state
    const modal = document.getElementById('viewConversationModal');
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';

    // Reset and show loading state
    document.getElementById('conversationTitle').textContent = 'Chargement...';
    document.getElementById('conversationDate').textContent = 'Chargement...';
    document.getElementById('conversationPlatform').textContent = 'Chargement...';
    document.getElementById('conversationMessages').innerHTML = '<div class="loading">Chargement des messages...</div>';

    // Fetch conversation details
    fetch(`/admin/conversations/${conversationId}`)
        .then(response => {
            console.log('API Response:', { status: response.status, statusText: response.statusText });
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('Conversation data received:', data);

            // Update conversation info
            document.getElementById('conversationTitle').textContent = data.title || 'Sans titre';
            document.getElementById('conversationDate').textContent = data.created_at || 'Date inconnue';
            document.getElementById('conversationPlatform').textContent = 
                data.platform.charAt(0).toUpperCase() + data.platform.slice(1);

            // Get messages container and clear loading state
            const messagesContainer = document.getElementById('conversationMessages');
            messagesContainer.innerHTML = '';

            if (data.messages && data.messages.length > 0) {
                data.messages.forEach(message => {
                    const messageElement = document.createElement('div');
                    messageElement.className = `message ${message.role}`;

                    messageElement.innerHTML = `
                        <div class="role">${message.role === 'user' ? 'Utilisateur' : 'Assistant'}</div>
                        <div class="content">${message.content}</div>
                        <div class="timestamp">${message.timestamp || ''}</div>
                    `;

                    messagesContainer.appendChild(messageElement);
                });

                // Scroll to the bottom of the messages
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            } else {
                messagesContainer.innerHTML = '<div class="empty-message">Aucun message dans cette conversation</div>';
            }
        })
        .catch(error => {
            console.error('Error fetching conversation:', error);
            // Show error in modal
            document.getElementById('conversationMessages').innerHTML = `
                <div class="error-message">Une erreur est survenue lors du chargement de la conversation.</div>
            `;
        });
}

function closeViewConversationModal() {
    const modal = document.getElementById('viewConversationModal');
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
}

// Initialize event listeners
document.addEventListener('DOMContentLoaded', function() {
    // Initialize navigation
    initializeNavigation();
    showSection('dashboard');
    fetchPlatformData('web');

    // User management event listeners
    document.querySelectorAll('.users-filters .filter-btn').forEach(btn => {
        btn.addEventListener('click', () => filterUsers(btn.getAttribute('data-filter')));
    });
    document.getElementById('userSearchInput').addEventListener('input', searchUsers);

    // Conversation management event listeners
    document.querySelectorAll('.conversations-filters .filter-btn').forEach(btn => {
        btn.addEventListener('click', () => filterConversations(btn.getAttribute('data-filter')));
    });
    document.getElementById('conversationSearchInput').addEventListener('input', searchConversations);

    // Modal handlers
    document.querySelector('#deleteConversationModal .close-modal').addEventListener('click', closeDeleteConversationModal);
    document.getElementById('cancelDeleteConversation').addEventListener('click', closeDeleteConversationModal);
    document.getElementById('confirmDeleteConversation').addEventListener('click', confirmDeleteConversation);
    document.querySelector('#viewConversationModal .close-modal').addEventListener('click', closeViewConversationModal);

    // Global click handler for modals
    window.addEventListener('click', function(event) {
        const deleteModal = document.getElementById('deleteConversationModal');
        const viewModal = document.getElementById('viewConversationModal');

        if (event.target === deleteModal) {
            closeDeleteConversationModal();
        } else if (event.target === viewModal) {
            closeViewConversationModal();
        }
    });
});