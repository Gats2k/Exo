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

  // Configurer les en-têtes du tableau pour afficher la structure standard
  const tableHeader = document.getElementById('usersTable').getElementsByTagName('thead')[0];
  // Vérifions si l'en-tête a une colonne ID, si oui, on la supprime pour revenir à la structure standard
  if (tableHeader.querySelector('tr th:first-child').innerText === 'ID') {
      tableHeader.innerHTML = `
      <tr>
          <th>Nom</th>
          <th>Prénom</th>
          <th>Âge</th>
          <th>Téléphone</th>
          <th>Niveau d'étude</th>
          <th>Date d'inscription</th>
      </tr>
      `;
  }

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
            <td colspan="6" class="see-more-cell" onclick="showSection('users')">Voir plus...</td>
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
            <td colspan="4" class="see-more-cell" onclick="showSection('conversations')">Voir plus...</td>
        `;
      }
  }
}

function updateTableWithPlatformData(data) {
    const usersTable = document.getElementById('usersTable').getElementsByTagName('tbody')[0];
    const conversationsTable = document.getElementById('conversationsTable').getElementsByTagName('tbody')[0];

    // Configurer les en-têtes du tableau en fonction de la plateforme
    const tableHeader = document.getElementById('usersTable').getElementsByTagName('thead')[0];

    if (data.platform === 'telegram') {
        // Configurer l'en-tête avec colonne ID pour Telegram
        tableHeader.innerHTML = `
        <tr>
            <th>ID</th>
            <th>Nom</th>
            <th>Prénom</th>
            <th>Âge</th>
            <th>Téléphone</th>
            <th>Niveau d'étude</th>
            <th>Date d'inscription</th>
        </tr>
        `;
    } else {
        // Configuration standard pour WhatsApp ou autres
        if (tableHeader.querySelector('tr th:first-child').innerText === 'ID') {
            tableHeader.innerHTML = `
            <tr>
                <th>Nom</th>
                <th>Prénom</th>
                <th>Âge</th>
                <th>Téléphone</th>
                <th>Niveau d'étude</th>
                <th>Date d'inscription</th>
            </tr>
            `;
        }
    }

    // Clear existing table data
    usersTable.innerHTML = '';
    conversationsTable.innerHTML = '';

    // Update users table
    if (data.users && data.users.length > 0) {
        // Display only first 5 rows
        const displayUsers = data.users.slice(0, 5);
        displayUsers.forEach(user => {
            const row = usersTable.insertRow();

            if (data.platform === 'telegram') {
                // Format Telegram avec colonne ID
                row.innerHTML = `
                    <td>${user.telegram_id || ''}</td>
                    <td>${user.last_name || '---'}</td>
                    <td>${user.first_name || '---'}</td>
                    <td>--</td>
                    <td>${user.phone || ''}</td>
                    <td>${user.study_level || ''}</td>
                    <td>${user.created_at || ''}</td>
                `;
            } else {
                // Format WhatsApp ou autre
                const name = data.platform === 'whatsapp' ? 
                    (user.name || `WhatsApp User ${user.phone || 'None'}`) : 
                    (user.name || '');

                row.innerHTML = `
                    <td>${name}</td>
                    <td>--</td>
                    <td>--</td>
                    <td>${user.phone || ''}</td>
                    <td>${user.study_level || ''}</td>
                    <td>${user.created_at || ''}</td>
                `;
            }
        });

        // Add "See more..." row if there are more than 5 users
        if (data.users.length >= 3) {
            const moreRow = usersTable.insertRow();
            moreRow.className = 'see-more-row';

            // Ajuster le colspan en fonction de la présence de la colonne ID
            const colSpan = data.platform === 'telegram' ? 7 : 6;

            moreRow.innerHTML = `
                <td colspan="${colSpan}" class="see-more-cell" onclick="showSection('users')">Voir plus...</td>
            `;
        }
    }

    // Update conversations table
    if (data.conversations && data.conversations.length > 0) {
        // Display only first 5 rows
        const displayConversations = data.conversations.slice(0, 5);
        displayConversations.forEach(conv => {
            // Ensure we have a numeric ID for the conversation
            const conversationId = conv.id ? conv.id : null;
            const row = conversationsTable.insertRow();
            row.innerHTML = `
                <td>${conv.title || 'Sans titre'}</td>
                <td>${conv.date || ''}</td>
                <td>${conv.time || ''}</td>
                <td>${conv.last_message || ''}</td>
            `;
        });

        if (data.conversations.length >= 3) {
            const moreRow = conversationsTable.insertRow();
            moreRow.className = 'see-more-row';
            moreRow.innerHTML = `
                <td colspan="4" class="see-more-cell" onclick="showSection('conversations')">Voir plus...</td>
            `;
        }
    }
}

// Ajouter une règle de style dans le document pour indiquer que les cellules "Voir plus..." sont cliquables
document.addEventListener('DOMContentLoaded', function() {
    // Créer une règle de style pour les cellules "Voir plus..."
    const style = document.createElement('style');
    style.innerHTML = `
        .see-more-cell {
            cursor: pointer;
            text-align: center;
            color: #ffd700;
            font-weight: bold;
        }
        .see-more-cell:hover {
            text-decoration: underline;
        }
    `;
    document.head.appendChild(style);
    
    // Configuration de Socket.IO pour les mises à jour en temps réel
    setupRealtimeUpdates();
});

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

    // Mise à jour des en-têtes du tableau en fonction de la plateforme
    const tableHeader = document.getElementById('fullUsersTable').getElementsByTagName('thead')[0];
    if (platform === 'telegram') {
        // S'assurer que la colonne ID est visible pour Telegram
        if (tableHeader.querySelector('tr th:first-child').innerText !== 'ID') {
            // Recréer les en-têtes avec ID pour Telegram
            tableHeader.innerHTML = `
            <tr>
                <th>ID</th>
                <th>Nom</th>
                <th>Prénom</th>
                <th>Âge</th>
                <th>Téléphone</th>
                <th>Niveau d'étude</th>
                <th>Date d'inscription</th>
                <th>Statut</th>
                <th>Actions</th>
            </tr>
            `;
        }
    } else {
        // Pour les autres plateformes, retirer la colonne ID s'il existe
        if (tableHeader.querySelector('tr th:first-child').innerText === 'ID') {
            // Recréer les en-têtes sans ID pour Web et WhatsApp
            tableHeader.innerHTML = `
            <tr>
                <th>Nom</th>
                <th>Prénom</th>
                <th>Âge</th>
                <th>Téléphone</th>
                <th>Niveau d'étude</th>
                <th>Date d'inscription</th>
                <th>Statut</th>
                <th>Actions</th>
            </tr>
            `;
        }
    }

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
            // Pour Telegram, utiliser directement l'ID Telegram
            userId = user.telegram_id || '';
        } else {
            // Pour WhatsApp, utiliser le numéro de téléphone
            userId = user.phone || '';
        }

        // Ajouter l'ID comme attribut de données à la ligne
        row.setAttribute('data-user-id', userId);

        if (platform === 'telegram') {
            // Pour Telegram, afficher l'ID, le nom et le prénom
            row.innerHTML = `
                <td>${user.telegram_id || ''}</td>
                <td>${user.last_name || '---'}</td>
                <td>${user.first_name || '---'}</td>
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
        } else if (platform === 'web') {
            // Pour Web, format standard
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
            // Pour WhatsApp
            const name = user.name || `WhatsApp User ${user.phone || 'None'}`;
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


function viewConversation(numericId) {
    if (!numericId) {
        console.error('No conversation ID provided');
        alert('Error: Unable to view conversation details');
        return;
    }

    // Obtenir le titre original correspondant à cet ID numérique
    const originalTitle = getTitleFromNumericId(numericId);

    console.log('Viewing conversation:', numericId, 'Original title:', originalTitle);

    // Si le titre commence par "Conversation thread_", c'est une conversation WhatsApp
    if (originalTitle && originalTitle.startsWith('Conversation thread_')) {
        // Extraire l'ID du thread directement
        const threadId = originalTitle.replace('Conversation ', '');
        console.log('WhatsApp thread detected:', threadId);

        // Pour les conversations WhatsApp, utiliser directement l'ID du thread
        fetch(`/admin/whatsapp/thread/${encodeURIComponent(threadId)}/messages`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                displayConversationMessages(data);
            })
            .catch(error => {
                console.error('Error fetching WhatsApp messages:', error);
                alert('Une erreur est survenue lors du chargement de la conversation WhatsApp');
            });
        return;
    }

    // Pour les autres types de conversations, utiliser la route par titre
    fetch(`/admin/conversations/by-title/${encodeURIComponent(originalTitle)}/messages`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            displayConversationMessages(data);
        })
        .catch(error => {
            console.error('Error fetching conversation messages:', error);
            alert('Une erreur est survenue lors du chargement de la conversation');
        });
}

function displayConversationMessages(data) {
    const messagesContainer = document.querySelector('#viewConversationModal .chat-messages');
    messagesContainer.innerHTML = '';

    if (!data.messages || data.messages.length === 0) {
        messagesContainer.innerHTML = '<div class="message system">Aucun message dans cette conversation</div>';
        return;
    }

    data.messages.forEach(message => {
        const messageElement = document.createElement('div');
        messageElement.className = `message ${message.role}`;

        const contentElement = document.createElement('div');
        contentElement.className = 'message-content';

        // Handle images if present
        if (message.image_url) {
            const img = document.createElement('img');
            img.src = message.image_url;
            img.style.maxWidth = '200px';
            img.style.borderRadius = '4px';
            img.style.marginBottom = '8px';
            contentElement.appendChild(img);
        }

        // Add message text
        contentElement.innerHTML += message.content;
        messageElement.appendChild(contentElement);
        messagesContainer.appendChild(messageElement);
    });

    // Show the modal
    const modal = document.getElementById('viewConversationModal');
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';

    // Scroll to the bottom of the messages
    const viewport = document.querySelector('#viewConversationModal .chat-viewport');
    viewport.scrollTop = viewport.scrollHeight;
}

function closeViewConversationModal() {
    const modal = document.getElementById('viewConversationModal');
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
}

let conversationIdToDelete = null;
let conversationTitleToDelete = null;

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

        // Utiliser l'ID existant ou créer un ID numérique basé sur le titre
        const conversationTitle = conversation.title || 'Sans titre';
        const numericId = conversation.id || getNumericIdForConversation(conversationTitle);

        row.innerHTML = `
            <td>${conversationTitle}</td>
            <td><span class="platform-badge ${platform}">${platform}</span></td>
            <td>${conversation.date || ''}</td>
            <td>${truncatedMessage}</td>
            <td><span class="status-badge ${isActive ? 'active' : 'archived'}">${isActive ? 'Active' : 'Archivée'}</span></td>
            <td class="action-buttons">
                <button class="action-btn view" onclick="viewConversation(${numericId})">
                    <i class="bi bi-eye"></i>
                </button>
                <button class="action-btn delete" onclick="deleteConversation(${numericId})">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        `;
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
        emptyState.querySelector('p').textContent = `Aucune conversation ${filter ==='active' ? 'active' : filter === 'archived' ? 'archivée' : ''} disponible`;
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

function deleteConversation(numericId) {
    conversationIdToDelete = numericId;
    // Stocke également le titre original pour la suppression
    conversationTitleToDelete = getTitleFromNumericId(numericId);
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
    if (conversationIdToDelete === null || !conversationTitleToDelete) return;

    fetch(`/admin/conversations/by-title/${encodeURIComponent(conversationTitleToDelete)}`, {
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

// À AJOUTER 
// Map global pour stocker les correspondances entre titres et IDs numériques
let conversationTitleToIdMap = {};
let nextConversationId = 1;

// Fonction utilitaire pour obtenir un ID numérique à partir d'un titre
function getNumericIdForConversation(title) {
    if (!title) return null;

    // Ajouter des logs pour comprendre ce qui se passe
    console.log('Getting numeric ID for title:', title);

    // Si nous n'avons pas encore d'ID pour ce titre, en créer un
    if (!conversationTitleToIdMap[title]) {
        conversationTitleToIdMap[title] = nextConversationId++;
        console.log('Created new ID:', conversationTitleToIdMap[title], 'for title:', title);
    } else {
        console.log('Using existing ID:', conversationTitleToIdMap[title], 'for title:', title);
    }

    return conversationTitleToIdMap[title];
}

// Fonction pour récupérer le titre original à partir de l'ID mappé
function getTitleFromNumericId(numericId) {
    for (const [title, id] of Object.entries(conversationTitleToIdMap)) {
        if (id === parseInt(numericId)) {
            return title;
        }
    }
    return null;
}

// Update the initialization code to include conversation handlers
document.addEventListener('DOMContentLoaded', function() {
    initializeNavigation();
    showSection('dashboard');
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

    // Add conversation-specific event listeners
    document.querySelectorAll('.conversations-filters .filter-btn').forEach(btn => {
        btn.addEventListener('click', () => filterConversations(btn.getAttribute('data-filter')));
    });

    document.getElementById('conversationSearchInput').addEventListener('input', searchConversations);

    // Conversation deletion modal handlers
    document.querySelector('#deleteConversationModal .close-modal').addEventListener('click', closeDeleteConversationModal);
    document.getElementById('cancelDeleteConversation').addEventListener('click', closeDeleteConversationModal);
    document.getElementById('confirmDeleteConversation').addEventListener('click', confirmDeleteConversation);

    window.addEventListener('click', function(event) {
        const modal = document.getElementById('deleteConversationModal');
        if (event.target === modal) {
            closeDeleteConversationModal();
        }
    });

    // Add conversation view modal handlers
    document.querySelector('#viewConversationModal .close-modal')
        .addEventListener('click', closeViewConversationModal);

    window.addEventListener('click', function(event) {
        const modal = document.getElementById('viewConversationModal');
        if (event.target === modal) {
            closeViewConversationModal();
        }
    });
});

// AI Model Settings
document.getElementById('ai-model').addEventListener('change', function(e) {
    const selectedModel = e.target.value;
    const openaiSettings = document.getElementById('openai-settings');
    const deepseekSettings = document.getElementById('deepseek-settings');
    const deepseekReasonerSettings = document.getElementById('deepseek-reasoner-settings');
    const qwenSettings = document.getElementById('qwen-settings');
    const geminiSettings = document.getElementById('gemini-settings');

    // Update visibility of settings panels
    openaiSettings.style.display = selectedModel === 'openai' ? 'block' : 'none';
    deepseekSettings.style.display = selectedModel === 'deepseek' ? 'block' : 'none';
    deepseekReasonerSettings.style.display = selectedModel === 'deepseek-reasoner' ? 'block' : 'none';
    qwenSettings.style.display = selectedModel === 'qwen' ? 'block' : 'none';
    geminiSettings.style.display = selectedModel === 'gemini' ? 'block' : 'none';
});

// Save AI Model Settings
document.getElementById('save-ai-settings').addEventListener('click', function() {
    const selectedModel = document.getElementById('ai-model').value;
    let data = {
        model: selectedModel
    };

    // Add instructions based on selected model
    if (selectedModel === 'deepseek') {
        const instructions = document.getElementById('deepseek-instructions').value;
        data.instructions = instructions;
    } else if (selectedModel === 'deepseek-reasoner') {
        const instructions = document.getElementById('deepseek-reasoner-instructions').value;
        data.instructions = instructions;
    } else if (selectedModel === 'qwen') {
        const instructions = document.getElementById('qwen-instructions').value;
        data.instructions = instructions;
    } else if (selectedModel === 'gemini') {
        const instructions = document.getElementById('gemini-instructions').value;
        data.instructions = instructions;
    }

    fetch('/admin/settings/model', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Les paramètres ont été sauvegardés avec succès. Le modèle est maintenant actif pour toutes les conversations.', 'success');
        } else {
            showNotification('Une erreur est survenue lors de la sauvegarde', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Une erreur est survenue lors de la sauvegarde', 'error');
    });
});

// Helper function to show notifications
function showNotification(message, type) {
    // You can implement this based on your notification system
    alert(message); // Basic implementation
}

function toggleMobileSidebar() {
    const sidebar = document.querySelector('.sidebar');
    sidebar.classList.toggle('mobile-visible');

    // Empêcher le défilement du corps quand la sidebar est ouverte
    if (sidebar.classList.contains('mobile-visible')) {
        document.body.style.overflow = 'hidden';
    } else {
        document.body.style.overflow = 'auto';
    }
}

// Fermer la sidebar si on clique en dehors
document.addEventListener('click', function(event) {
    const sidebar = document.querySelector('.sidebar');
    const mobileToggle = document.querySelector('.mobile-toggle');

    if (sidebar.classList.contains('mobile-visible') && 
        !sidebar.contains(event.target) && 
        !mobileToggle.contains(event.target)) {

        // Ferme la sidebar
        sidebar.classList.remove('mobile-visible');

        // Met également à jour l'état du bouton pour changer l'icône
        mobileToggle.classList.remove('active');

        // Réactive le défilement
        document.body.style.overflow = 'auto';

        // Reset des styles inline quand on ferme
        setTimeout(() => {
            if (!sidebar.classList.contains('mobile-visible')) {
                sidebar.style.width = '';

                document.querySelectorAll('.sidebar .nav-item').forEach(item => {
                    item.style.width = '';
                    item.style.height = '';
                    item.style.padding = '';
                    item.style.justifyContent = '';
                });

                document.querySelectorAll('.sidebar .nav-item span').forEach(span => {
                    span.style.display = '';
                    span.style.marginLeft = '';
                });

                document.querySelectorAll('.sidebar-section').forEach(section => {
                    section.style.padding = '';
                    section.style.alignItems = '';
                });

                if (document.querySelector('.sidebar-footer')) {
                    document.querySelector('.sidebar-footer').style.display = '';
                    document.querySelector('.sidebar-footer').style.opacity = '';
                }
            }
        }, 300); // Attendre la fin de l'animation
    }
});

function toggleMobileSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const mobileToggle = document.querySelector('.mobile-toggle');

    // Si la sidebar n'est pas déjà ouverte, on prépare son affichage
    if (!sidebar.classList.contains('mobile-visible')) {
        // Assure que tous les styles sont appliqués avant l'animation
        sidebar.style.width = '250px';

        document.querySelectorAll('.sidebar .nav-item').forEach(item => {
            item.style.width = '100%';
            item.style.height = 'auto';
            item.style.padding = '12px';
            item.style.justifyContent = 'flex-start';
        });

        document.querySelectorAll('.sidebar .nav-item span').forEach(span => {
            span.style.display = 'inline';
            span.style.marginLeft = '12px';
        });

        document.querySelectorAll('.sidebar-section').forEach(section => {
            section.style.padding = '15px';
            section.style.alignItems = 'stretch';
        });

        if (document.querySelector('.sidebar-footer')) {
            document.querySelector('.sidebar-footer').style.display = 'block';
            document.querySelector('.sidebar-footer').style.opacity = '1';
        }
    }

    // Bascule la classe pour l'animation
    sidebar.classList.toggle('mobile-visible');

    // Bascule la classe active du bouton pour changer l'icône
    mobileToggle.classList.toggle('active');

    // Gestion du défilement
    if (sidebar.classList.contains('mobile-visible')) {
        document.body.style.overflow = 'hidden';
    } else {
        document.body.style.overflow = 'auto';

        // Reset des styles inline quand on ferme
        setTimeout(() => {
            if (!sidebar.classList.contains('mobile-visible')) {
                sidebar.style.width = '';

                document.querySelectorAll('.sidebar .nav-item').forEach(item => {
                    item.style.width = '';
                    item.style.height = '';
                    item.style.padding = '';
                    item.style.justifyContent = '';
                });

                document.querySelectorAll('.sidebar .nav-item span').forEach(span => {
                    span.style.display = '';
                    span.style.marginLeft = '';
                });

                document.querySelectorAll('.sidebar-section').forEach(section => {
                    section.style.padding = '';
                    section.style.alignItems = '';
                });

                if (document.querySelector('.sidebar-footer')) {
                    document.querySelector('.sidebar-footer').style.display = '';
                    document.querySelector('.sidebar-footer').style.opacity = '';
                }
            }
        }, 300); // Attendre la fin de l'animation
    }
}

/* À AJOUTER */
// Fonction pour envelopper tous les tableaux dans des conteneurs défilables sur mobile
function setupResponsiveTables() {
    if (window.innerWidth <= 768) {
        document.querySelectorAll('.data-table').forEach(table => {
            // Vérifier si le tableau n'est pas déjà enveloppé
            if (!table.parentElement.classList.contains('table-responsive-container')) {
                // Créer le conteneur
                const container = document.createElement('div');
                container.className = 'table-responsive-container';

                // Créer les indicateurs de défilement
                const leftIndicator = document.createElement('div');
                leftIndicator.className = 'scroll-indicator scroll-left';
                leftIndicator.innerHTML = '<i class="bi bi-chevron-left"></i>';

                const rightIndicator = document.createElement('div');
                rightIndicator.className = 'scroll-indicator scroll-right';
                rightIndicator.innerHTML = '<i class="bi bi-chevron-right"></i>';

                // Envelopper le tableau
                table.parentNode.insertBefore(container, table);
                container.appendChild(table);
                container.appendChild(leftIndicator);
                container.appendChild(rightIndicator);

                // Ajouter l'événement de défilement
                container.addEventListener('scroll', function() {
                    updateScrollIndicators(container);
                });

                // Initialiser l'état des indicateurs
                updateScrollIndicators(container);
            }
        });
    }
}

// Mettre à jour les indicateurs de défilement
function updateScrollIndicators(container) {
    const leftIndicator = container.querySelector('.scroll-left');
    const rightIndicator = container.querySelector('.scroll-right');

    // Afficher/masquer l'indicateur gauche
    if (container.scrollLeft > 10) {
        leftIndicator.style.display = 'flex';
    } else {
        leftIndicator.style.display = 'none';
    }

    // Afficher/masquer l'indicateur droit
    if (container.scrollLeft + container.clientWidth >= container.scrollWidth - 10) {
        rightIndicator.style.display = 'none';
    } else {
        rightIndicator.style.display = 'flex';
    }
}

/**
 * Configure Socket.IO pour recevoir les mises à jour en temps réel des statistiques
 */
// Système de notifications - variables globales
let notifications = [];
const MAX_NOTIFICATIONS = 5;

// Ouvrir/fermer le menu de notifications
function toggleNotifications() {
    const notificationDropdown = document.getElementById('notificationDropdown');
    notificationDropdown.classList.toggle('show');
    
    // Si le menu est affiché, marquons les notifications comme lues
    if (notificationDropdown.classList.contains('show')) {
        document.getElementById('notification-badge').classList.remove('show');
    }
    
    // Fermer le menu déroulant des plateformes si ouvert
    document.getElementById('platformDropdown').classList.remove('show');
    
    // Empêcher la propagation de l'événement de clic
    event.stopPropagation();
}

// Ajout d'une nouvelle notification
function addNotification(message, type = 'info') {
    // Créer un nouvel objet notification
    const newNotification = {
        id: Date.now(),
        message: message,
        type: type,
        timestamp: new Date()
    };
    
    // Ajouter au début de la liste de notifications
    notifications.unshift(newNotification);
    
    // Limiter le nombre de notifications stockées
    if (notifications.length > MAX_NOTIFICATIONS) {
        notifications.pop();
    }
    
    // Afficher le badge de notification
    document.getElementById('notification-badge').classList.add('show');
    
    // Mettre à jour l'affichage des notifications
    updateNotificationsDisplay();
}

// Mise à jour de l'affichage des notifications
function updateNotificationsDisplay() {
    const notificationList = document.getElementById('notification-list');
    const emptyNotifications = document.getElementById('empty-notifications');
    
    // Vider la liste actuelle
    while (notificationList.firstChild && notificationList.firstChild !== emptyNotifications) {
        notificationList.removeChild(notificationList.firstChild);
    }
    
    // Afficher le message "Aucune notification" si la liste est vide
    if (notifications.length === 0) {
        emptyNotifications.style.display = 'block';
        return;
    } else {
        emptyNotifications.style.display = 'none';
    }
    
    // Ajouter chaque notification à la liste
    notifications.forEach(notification => {
        const notificationItem = document.createElement('div');
        notificationItem.className = 'notification-item';
        notificationItem.dataset.id = notification.id;
        
        const content = document.createElement('div');
        content.className = 'notification-content';
        content.textContent = notification.message;
        
        const time = document.createElement('div');
        time.className = 'notification-time';
        time.textContent = formatTimestamp(notification.timestamp);
        
        notificationItem.appendChild(content);
        notificationItem.appendChild(time);
        
        // Ajouter un gestionnaire d'événements pour supprimer la notification au clic
        notificationItem.addEventListener('click', function() {
            removeNotification(notification.id);
        });
        
        notificationList.insertBefore(notificationItem, emptyNotifications);
    });
}

// Formater l'horodatage pour l'affichage
function formatTimestamp(timestamp) {
    const now = new Date();
    const diff = now - timestamp;
    
    // Si moins d'une minute
    if (diff < 60000) {
        return 'À l\'instant';
    }
    
    // Si moins d'une heure
    if (diff < 3600000) {
        const minutes = Math.floor(diff / 60000);
        return `Il y a ${minutes} minute${minutes > 1 ? 's' : ''}`;
    }
    
    // Si aujourd'hui
    if (now.toDateString() === timestamp.toDateString()) {
        return `Aujourd'hui à ${timestamp.getHours()}:${String(timestamp.getMinutes()).padStart(2, '0')}`;
    }
    
    // Sinon, date complète
    return `${timestamp.toLocaleDateString()} à ${timestamp.getHours()}:${String(timestamp.getMinutes()).padStart(2, '0')}`;
}

// Supprimer une notification
function removeNotification(id) {
    notifications = notifications.filter(notification => notification.id !== id);
    updateNotificationsDisplay();
    
    // Si toutes les notifications sont supprimées, cacher le badge
    if (notifications.length === 0) {
        document.getElementById('notification-badge').classList.remove('show');
    }
}

// Supprimer toutes les notifications
function clearAllNotifications() {
    notifications = [];
    updateNotificationsDisplay();
    document.getElementById('notification-badge').classList.remove('show');
}

// Fermer le menu de notifications quand on clique ailleurs sur la page
document.addEventListener('click', function(event) {
    const notificationDropdown = document.getElementById('notificationDropdown');
    const notificationBell = document.querySelector('.notification-bell');
    
    if (!notificationBell.contains(event.target) && !notificationDropdown.contains(event.target)) {
        notificationDropdown.classList.remove('show');
    }
});

// Socket.IO singleton pour éviter les connexions multiples
let socketInstance = null;

function setupRealtimeUpdates() {
    // Vérifier si la variable socket existe déjà (peut être créée dans main.js)
    if (typeof io !== 'undefined') {
        // Réutiliser l'instance existante ou en créer une nouvelle si nécessaire
        if (!socketInstance) {
            socketInstance = io();

            // Ajouter un écouteur d'événement une seule fois
            socketInstance.on('feedback_stats_updated', function(data) {
                console.log('Received real-time feedback stats update:', data);

                // Mettre à jour uniquement la statistique de satisfaction
                if (data.satisfaction_rate !== undefined) {
                    // Mettre à jour l'affichage du taux de satisfaction
                    document.querySelectorAll('.stat-value')[2].textContent = `${data.satisfaction_rate}%`;

                    // Ajouter une animation pour attirer l'attention sur la mise à jour
                    const satisfactionElement = document.querySelectorAll('.stat-card')[2];
                    satisfactionElement.classList.add('highlight-update');

                    // Supprimer la classe d'animation après un court délai
                    setTimeout(() => {
                        satisfactionElement.classList.remove('highlight-update');
                    }, 2000);

                    // Ajouter une notification pour la mise à jour
                    addNotification(`Taux de satisfaction mis à jour: ${data.satisfaction_rate}%`, 'info');
                }
            });

            // Configuration des écouteurs d'événements pour Telegram
            setupTelegramUpdates();

            // Configuration des écouteurs d'événements pour WhatsApp
            setupWhatsAppUpdates();

            // Configuration des écouteurs d'événements pour le Web
            setupWebUpdates();
            
            // Listener for model settings updates - shows notification when model changes
            socketInstance.on('model_settings_updated', function(data) {
                console.log('AI model settings updated:', data);
                // Show a notification to all admins viewing the dashboard
                addNotification(`Modèle IA mis à jour: ${data.model}`, 'success');
            });

            console.log('Socket.IO initialisé avec succès pour les mises à jour en temps réel');
        }
    } else {
        console.error("Socket.IO n'est pas disponible. Vérifiez que la bibliothèque est bien chargée.");
    }
}

function setupTelegramUpdates() {
    if (typeof io !== 'undefined' && socketInstance) {
        // Écouteur pour les nouveaux utilisateurs Telegram
        socketInstance.on('new_telegram_user', function(userData) {
            console.log('Received new Telegram user:', userData);

            // Mettre à jour les statistiques du tableau de bord
            updateDashboardStatistics(userData.platform);

            // Animer la carte des utilisateurs pour attirer l'attention
            const userStatsElement = document.querySelectorAll('.stat-card')[0];
            if (userStatsElement) {
                userStatsElement.classList.add('highlight-update');
                setTimeout(() => {
                    userStatsElement.classList.remove('highlight-update');
                }, 2000);
            }

            // Ajouter une notification
            addNotification(`Nouvel utilisateur Telegram: ${userData.first_name} ${userData.last_name}`, 'info');

            // Mettre à jour la liste des utilisateurs si nous sommes dans la section utilisateurs
            if (document.getElementById('users-section').style.display === 'block') {
                fetchAllUsers(currentPlatform);
            }
        });

        // Écouteur pour les nouvelles conversations Telegram
        socketInstance.on('new_telegram_conversation', function(conversationData) {
            console.log('Received new Telegram conversation:', conversationData);

            // Mettre à jour les statistiques du tableau de bord
            updateDashboardStatistics(conversationData.platform);

            // Animer la carte des conversations pour attirer l'attention
            const conversationStatsElement = document.querySelectorAll('.stat-card')[1];
            if (conversationStatsElement) {
                conversationStatsElement.classList.add('highlight-update');
                setTimeout(() => {
                    conversationStatsElement.classList.remove('highlight-update');
                }, 2000);
            }

            // Ajouter une notification
            addNotification(`Nouvelle conversation Telegram: ${conversationData.title}`, 'info');

            // Mettre à jour la liste des conversations si nous sommes dans la section conversations
            if (document.getElementById('conversations-section').style.display === 'block') {
                fetchAllConversations(currentPlatform);
            }
        });

        console.log('Telegram update listeners configured successfully');
    } else {
        console.error("Socket.IO n'est pas disponible pour les mises à jour Telegram");
    }
}

/* À AJOUTER */
function setupWhatsAppUpdates() {
    if (typeof io !== 'undefined' && socketInstance) {
        // Écouteur pour les nouveaux utilisateurs WhatsApp
        socketInstance.on('new_whatsapp_user', function(userData) {
            console.log('Received new WhatsApp user:', userData);

            // Mettre à jour les statistiques du tableau de bord
            updateDashboardStatistics(userData.platform);

            // Animer la carte des utilisateurs pour attirer l'attention
            const userStatsElement = document.querySelectorAll('.stat-card')[0];
            if (userStatsElement) {
                userStatsElement.classList.add('highlight-update');
                setTimeout(() => {
                    userStatsElement.classList.remove('highlight-update');
                }, 2000);
            }

            // Ajouter une notification
            addNotification(`Nouvel utilisateur WhatsApp: ${userData.name || userData.phone}`, 'info');

            // Mettre à jour la liste des utilisateurs si nous sommes dans la section utilisateurs
            if (document.getElementById('users-section').style.display === 'block') {
                fetchAllUsers(currentPlatform);
            }
        });

        // Écouteur pour les nouvelles conversations WhatsApp
        socketInstance.on('new_whatsapp_conversation', function(conversationData) {
            console.log('Received new WhatsApp conversation:', conversationData);

            // Mettre à jour les statistiques du tableau de bord
            updateDashboardStatistics(conversationData.platform);

            // Animer la carte des conversations pour attirer l'attention
            const conversationStatsElement = document.querySelectorAll('.stat-card')[1];
            if (conversationStatsElement) {
                conversationStatsElement.classList.add('highlight-update');
                setTimeout(() => {
                    conversationStatsElement.classList.remove('highlight-update');
                }, 2000);
            }

            // Ajouter une notification
            addNotification(`Nouvelle conversation WhatsApp: ${conversationData.title}`, 'info');

            // Mettre à jour la liste des conversations si nous sommes dans la section conversations
            if (document.getElementById('conversations-section').style.display === 'block') {
                fetchAllConversations(currentPlatform);
            }
        });

        console.log('WhatsApp update listeners configured successfully');
    } else {
        console.error("Socket.IO n'est pas disponible pour les mises à jour WhatsApp");
    }
}

function setupWebUpdates() {
    if (typeof io !== 'undefined' && socketInstance) {
        // Écouteur pour les nouveaux utilisateurs Web
        socketInstance.on('new_web_user', function(userData) {
            console.log('Received new Web user:', userData);

            // Mettre à jour les statistiques du tableau de bord
            updateDashboardStatistics('web');

            // Animer la carte des utilisateurs pour attirer l'attention
            const userStatsElement = document.querySelectorAll('.stat-card')[0];
            if (userStatsElement) {
                userStatsElement.classList.add('highlight-update');
                setTimeout(() => {
                    userStatsElement.classList.remove('highlight-update');
                }, 2000);
            }

            // Ajouter une notification
            addNotification(`Nouvel utilisateur Web: ${userData.first_name} ${userData.last_name}`, 'info');

            // Mettre à jour la liste des utilisateurs si nous sommes dans la section utilisateurs
            if (document.getElementById('users-section').style.display === 'block') {
                fetchAllUsers(currentPlatform);
            }
        });

        // Écouteur pour les nouvelles conversations Web
        socketInstance.on('new_web_conversation', function(conversationData) {
            console.log('Received new Web conversation:', conversationData);

            // Mettre à jour les statistiques du tableau de bord
            updateDashboardStatistics('web');

            // Animer la carte des conversations pour attirer l'attention
            const conversationStatsElement = document.querySelectorAll('.stat-card')[1];
            if (conversationStatsElement) {
                conversationStatsElement.classList.add('highlight-update');
                setTimeout(() => {
                    conversationStatsElement.classList.remove('highlight-update');
                }, 2000);
            }

            // Ajouter une notification
            addNotification(`Nouvelle conversation Web: ${conversationData.title}`, 'info');

            // Mettre à jour la liste des conversations si nous sommes dans la section conversations
            if (document.getElementById('conversations-section').style.display === 'block') {
                fetchAllConversations(currentPlatform);
            }
        });

        console.log('Web update listeners configured successfully');
    } else {
        console.error("Socket.IO n'est pas disponible pour les mises à jour Web");
    }
}

// Fonction pour mettre à jour les statistiques du tableau de bord
function updateDashboardStatistics(platform) {
    // Ne mettre à jour que si la plateforme actuellement affichée correspond
    if (currentPlatform === platform || currentPlatform === 'all') {
        fetchPlatformData(currentPlatform);
    }
}

function updateDashboardCounts() {
    // On vérifie que nous sommes sur la page dashboard
    if (document.getElementById('dashboard-section').style.display === 'block') {
        // Mettre à jour les statistiques générales
        fetch(`/admin/data/${currentPlatform}/stats`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                // Mettre à jour le nombre d'utilisateurs actifs
                const activeUsersElement = document.querySelectorAll('.stat-value')[0];
                if (activeUsersElement) {
                    activeUsersElement.textContent = data.active_users;

                    // Animation pour attirer l'attention
                    const userStatsElement = document.querySelectorAll('.stat-card')[0];
                    userStatsElement.classList.add('highlight-update');
                    setTimeout(() => {
                        userStatsElement.classList.remove('highlight-update');
                    }, 2000);
                }

                // Mettre à jour le nombre d'utilisateurs actifs aujourd'hui
                const activeUsersTodayElement = document.querySelectorAll('.stat-subtitle')[0];
                if (activeUsersTodayElement) {
                    activeUsersTodayElement.textContent = `+${data.active_users_today} aujourd'hui`;
                }

                // Mettre à jour le nombre de conversations aujourd'hui
                const todayConversationsElement = document.querySelectorAll('.stat-value')[1];
                if (todayConversationsElement) {
                    todayConversationsElement.textContent = data.today_conversations;

                    // Animation pour attirer l'attention
                    const convStatsElement = document.querySelectorAll('.stat-card')[1];
                    convStatsElement.classList.add('highlight-update');
                    setTimeout(() => {
                        convStatsElement.classList.remove('highlight-update');
                    }, 2000);
                }
            })
            .catch(error => {
                console.error('Error fetching dashboard stats:', error);
            });
    }
}

// Exécuter au chargement et lors du redimensionnement
document.addEventListener('DOMContentLoaded', function() {
    // Configurer les tableaux responsive
    setupResponsiveTables();
    
    // Configurer les mises à jour en temps réel pour les statistiques de feedback
    setupRealtimeUpdates();

    // Reconfigurer les tableaux si la fenêtre est redimensionnée
    window.addEventListener('resize', function() {
        setupResponsiveTables();
    });

    // Observer les changements de DOM pour détecter les nouveaux tableaux
    if (window.MutationObserver) {
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.addedNodes.length > 0) {
                    setupResponsiveTables();
                }
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });
    }
});