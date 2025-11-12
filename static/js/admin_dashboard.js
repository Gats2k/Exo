let currentUserPage = 1;
let userPagination = {}; // Stockera les infos de pagination des users
let currentConversationPage = 1;
let conversationPagination = {}; // Stockera les infos de pagination des convos
let currentUserFilter = { status: null, search: null }; // status: 'active'/'inactive' ou null
let currentConversationFilter = { status: null, search: null }; // status: 'active'/'archived' ou null
let searchDebounceTimeout = null; // Pour le délai de recherche (debounce)
const ITEMS_PER_PAGE = 20; // Ou la valeur par défaut définie dans votre backend

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

    // Fetch appropriate data based on section (load page 1)
    if (sectionId === 'users') {
        currentUserPage = 1;
        // S'assurer de passer les filtres vides initialement si besoin
        fetchAllUsers(currentPlatform, currentUserPage, { status: null, search: null });
    } else if (sectionId === 'conversations') {
        currentConversationPage = 1;
         // S'assurer de passer les filtres vides initialement si besoin
        fetchAllConversations(currentPlatform, currentConversationPage, { status: null, search: null });
    } else if (sectionId === 'subscriptions') { // <-- AJOUTER CE CAS
        // On pourrait avoir une pagination/filtre pour les abos aussi à terme
        fetchAllSubscriptions(currentPlatform, 1); // Appel de la nouvelle fonction
    } else if (sectionId === 'dashboard') {
        fetchPlatformData(currentPlatform);
    }
}

function initializeNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const section = item.getAttribute('data-section');
            showSection(section);
        });
    });
}

function filterUsers(statusFilter) {
    console.log(`Filtering users by status: ${statusFilter}`);
    // Mettre à jour l'état global des filtres utilisateur
    currentUserFilter.status = (statusFilter === 'all') ? null : statusFilter;
    currentUserFilter.search = null; // Réinitialiser la recherche quand on filtre par statut

    // Réinitialiser visuellement la barre de recherche
    document.getElementById('userSearchInput').value = '';

    // Mettre à jour l'état actif des boutons de filtre DANS LA SECTION USER
    document.querySelectorAll('#users-section .filter-buttons .filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-filter') === statusFilter);
    });

    // Appeler fetchAllUsers avec le nouveau filtre, en commençant à la page 1
    fetchAllUsers(currentPlatform, 1, currentUserFilter);
}

function searchUsers() {
    // Utiliser un délai (debounce) pour éviter trop d'appels API pendant la frappe
    clearTimeout(searchDebounceTimeout); // Annuler le timeout précédent

    const searchTerm = document.getElementById('userSearchInput').value;

    searchDebounceTimeout = setTimeout(() => {
        console.log(`Searching users with term: "${searchTerm}"`);
        // Mettre à jour l'état global
        currentUserFilter.search = searchTerm.trim(); // Enlever espaces début/fin
        currentUserFilter.status = null; // Réinitialiser le filtre statut quand on recherche

        // Réinitialiser visuellement les filtres statut (mettre 'Tous' en actif) DANS LA SECTION USER
        document.querySelectorAll('#users-section .filter-buttons .filter-btn').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-filter') === 'all');
        });

        // Appeler fetchAllUsers avec la recherche, page 1
        fetchAllUsers(currentPlatform, 1, currentUserFilter);
    }, 500); // Délai de 500ms après la dernière frappe
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
    // Réinitialiser les filtres et la page lors du changement de plateforme
    currentUserFilter = { status: null, search: null };
    currentConversationFilter = { status: null, search: null };
    currentUserPage = 1;
    currentConversationPage = 1;

    if (currentSection === 'users') {
        fetchAllUsers(platform, 1, currentUserFilter); // Page 1, sans filtre
    } else if (currentSection === 'conversations') {
        fetchAllConversations(platform, 1, currentConversationFilter); // Page 1, sans filtre
    } else { // Dashboard ou autre
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
            const truncatedMessage = conv.last_message ?
                (conv.last_message.length > 50 ? conv.last_message.substring(0, 50) + '...' : conv.last_message) :
                '';
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

// Accepte maintenant un objet filterParams { status: '...', search: '...' }
function fetchAllUsers(platform, page = 1, filterParams = {}) {
    console.log(`Workspaceing users for platform: ${platform}, page: ${page}, filters:`, filterParams);

    const params = new URLSearchParams({
        page: page,
        per_page: ITEMS_PER_PAGE
    });
    if (filterParams.status && filterParams.status !== 'all') {
        params.append('status', filterParams.status);
    }
    if (filterParams.search && filterParams.search.trim() !== '') {
        params.append('search', filterParams.search.trim());
    }
    const url = `/admin/users/${platform}?${params.toString()}`;

    // TODO: (Optionnel) Afficher un spinner/indicateur de chargement ici

    fetch(url)
        .then(response => {
             if (!response.ok) {
                 // Essayer de lire l'erreur JSON du backend
                 return response.json().catch(() => {
                    throw new Error(`Erreur HTTP ${response.status} (${response.statusText}) pour ${url}`);
                 }).then(errData => {
                    throw new Error(errData.error || `Erreur HTTP ${response.status}`);
                 });
             }
             // Si la réponse est OK, mettre à jour l'état global du filtre *avant* de traiter
             currentUserFilter = { ...filterParams }; // Mémorise le filtre utilisé pour cet appel réussi
             return response.json();
        })
        .then(data => {
            // console.log(`Data received for ${platform} users page ${page} with filters:`, data);
            if (data.users && data.pagination) { // Vérifier que les clés nécessaires existent
                 updateFullUsersTable(data.users, platform); // Met à jour le tableau
                 userPagination = data.pagination; // Stocke les infos de pagination
                 currentUserPage = data.pagination.current_page; // Met à jour la page actuelle

                console.log('--- Pagination Users Reçue (fetchAllUsers) ---');
                console.log(userPagination); // Affiche l'objet reçu

                 renderUserPaginationControls(userPagination); // Affiche/Met à jour les boutons

                 // Gérer l'état vide si la liste d'utilisateurs est vide
                 if(data.users.length === 0) {
                    showEmptyState('fullUsersTableContainer', platform, 'users'); // Affiche l'état vide
                    // Personnaliser le message si un filtre ou une recherche est actif
                    const emptyStateP = document.querySelector('#fullUsersTableContainer .empty-state p');
                    if(emptyStateP) { // Vérifier si l'élément p existe
                        if (currentUserFilter.status || (currentUserFilter.search && currentUserFilter.search.trim() !== '')) {
                             emptyStateP.textContent = "Aucun utilisateur ne correspond à vos critères.";
                        } else {
                             const platformName = platform === 'web' ? 'Web' : platform.charAt(0).toUpperCase() + platform.slice(1);
                             emptyStateP.textContent = `Aucun utilisateur ${platformName} disponible pour le moment`;
                        }
                    }
                 }
            } else {
                // Si la structure de données n'est pas celle attendue
                 console.error("Données reçues invalides du serveur:", data);
                 showEmptyState('fullUsersTableContainer', platform, 'users');
                 renderUserPaginationControls({}); // Cacher pagination
            }
             // TODO: (Optionnel) Cacher le spinner/indicateur de chargement ici
        })
        .catch(error => {
            console.error(`Error fetching ${platform} users page ${page} with filters:`, error);
            showEmptyState('fullUsersTableContainer', platform, 'users'); // Afficher état vide en cas d'erreur
             userPagination = {}; // Réinitialiser
             renderUserPaginationControls(userPagination); // Cacher pagination
             // Afficher un message d'erreur plus visible à l'utilisateur si besoin
             const emptyStateP = document.querySelector('#fullUsersTableContainer .empty-state p');
             if(emptyStateP) emptyStateP.textContent = `Erreur lors du chargement: ${error.message}`;
             // TODO: (Optionnel) Cacher le spinner/indicateur de chargement ici
        });
}

function updateFullUsersTable(users, platform) {
    const tableBody = document.getElementById('fullUsersTable').getElementsByTagName('tbody')[0];
    const tableElement = document.getElementById('fullUsersTable');
    const container = document.getElementById('fullUsersTableContainer');
    const emptyState = container.querySelector('.empty-state');

    // Vider le contenu précédent du tableau !
    tableBody.innerHTML = '';

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

}

function showEmptyState(containerId, platform, type = 'users') {
    const container = document.getElementById(containerId);
    const emptyState = container.querySelector('.empty-state');
    const table = container.querySelector('table');

    // Cacher le tableau et montrer l'état vide
    if (table) table.style.display = 'none';
    emptyState.style.display = 'flex';

    // Personnaliser le message selon la plateforme et le type
    const pElement = emptyState.querySelector('p');
    if (pElement) {
         // Utiliser le paramètre 'type' passé à la fonction
         const platformName = platform === 'web' ? 'Web' : platform.charAt(0).toUpperCase() + platform.slice(1);
         if (type === 'users') {
             pElement.textContent = `Aucun utilisateur ${platformName} disponible pour le moment`;
         } else if (type === 'conversations') {
              pElement.textContent = `Aucune conversation ${platformName} disponible pour le moment`;
         } else if (type === 'subscriptions') { // <-- AJOUTER CE CAS
              pElement.textContent = `Aucun abonnement ${platformName} disponible pour le moment`;
         } else {
             pElement.textContent = `Aucune donnée disponible pour le moment`; // Message par défaut
         }
         // Adapter le message si un filtre/recherche est actif (logique copiée/adaptée de fetchAllUsers/fetchAllConversations)
          if ((type === 'users' && (currentUserFilter.status || currentUserFilter.search)) ||
              (type === 'conversations' && (currentConversationFilter.status || currentConversationFilter.search)) ||
              (type === 'subscriptions' && (/* prévoir variables filtre abo ici */ false)) ) { // Adapter pour les filtres abonnements plus tard
                 pElement.textContent = `Aucun ${type} ne correspond à vos critères.`;
             }
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

        // Rafraîchir la page ACTUELLE des utilisateurs
        fetchAllUsers(currentPlatform, currentUserPage); // <-- MODIFIÉE : Ajout de currentUserPage
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


function viewConversation(identifier, platformType) { // <<< Signature modifiée
    if (identifier === undefined || identifier === null || identifier === '') { // Vérification plus robuste
        console.error('No conversation identifier provided for platform:', platformType);
        alert('Erreur: Impossible d\'afficher les détails de la conversation (ID manquant ou invalide)');
        return;
    }

    console.log(`Viewing conversation for platform [${platformType}] with identifier:`, identifier); // Log adapté

    // Store the current conversation ID and platform type for admin message sending
    window.currentViewedConversation = {
        id: identifier,
        platform: platformType
    };

    let fetchUrl;

    // --- NOUVEAU : Sélection de l'URL backend basée sur platformType ---
    if (platformType === 'whatsapp') {
        // WhatsApp utilise toujours l'URL basée sur le thread_id
        fetchUrl = `/admin/whatsapp/thread/${encodeURIComponent(identifier)}/messages`;
        console.log("Using WhatsApp specific URL:", fetchUrl);
    } else if (platformType === 'web' || platformType === 'telegram') {
        // Web et Telegram utilisent la NOUVELLE URL basée sur l'ID numérique
        fetchUrl = `/admin/conversations/${identifier}/messages`; // <<< NOUVELLE URL par ID
        console.log("Using Web/Telegram URL by ID:", fetchUrl);
    } else {
        // Cas d'erreur si la plateforme n'est pas supportée
        console.error(`Unsupported platform type for viewing: ${platformType}`);
        alert(`Erreur: Le type de plateforme '${platformType}' n'est pas supporté pour la visualisation.`);
        return;
    }

    // --- MODIFIÉ : Fetch unique avec gestion d'erreur améliorée ---
    fetch(fetchUrl)
        .then(response => {
            if (!response.ok) {
                // Essayer de lire le corps de l'erreur s'il existe (souvent en JSON)
                return response.json().catch(() => {
                    // Si le corps n'est pas JSON ou est vide, créer une erreur standard
                    throw new Error(`Erreur HTTP ${response.status} (${response.statusText})`);
                }).then(errorData => {
                    // Si on a pu lire le JSON d'erreur, l'utiliser
                    throw new Error(errorData.error || `Erreur HTTP ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
             // Vérifier si le backend a renvoyé une erreur dans le JSON même avec un status 200 OK
             if (data.error) {
                  throw new Error(data.error);
             }
             // Si tout va bien, afficher les messages
            displayConversationMessages(data);
        })
        .catch(error => {
            // Gérer toutes les erreurs (réseau, HTTP, JSON, erreurs applicatives)
            console.error('Error fetching or processing conversation messages:', error);
            alert(`Une erreur est survenue lors du chargement de la conversation: ${error.message}`);

            // Afficher un message d'erreur dans le modal
            const messagesContainer = document.querySelector('#viewConversationModal .chat-messages');
            if (messagesContainer) {
                messagesContainer.innerHTML = `<div class="message system error">Erreur: Impossible de charger les messages.<br>(${error.message})</div>`;
            }
             // Optionnel : ouvrir quand même le modal pour montrer l'erreur
             const modal = document.getElementById('viewConversationModal');
             if (modal) {
                 modal.style.display = 'block';
                 document.body.style.overflow = 'hidden'; // Empêcher le défilement de l'arrière-plan
             }
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

    // Clear the current conversation data when closing the modal
    window.currentViewedConversation = null;

    // Clear the admin message input
    const adminMessageInput = document.getElementById('adminMessageInput');
    if (adminMessageInput) {
        adminMessageInput.value = '';
    }
}

function sendAdminMessage() {
    if (!window.currentViewedConversation || !window.currentViewedConversation.id) {
        console.error('No active conversation to send admin message to');
        alert('Erreur: Aucune conversation active pour envoyer le message.');
        return;
    }

    const adminMessageInput = document.getElementById('adminMessageInput');
    const messageContent = adminMessageInput.value.trim();

    if (!messageContent) {
        console.log('Cannot send empty admin message');
        return;
    }

    const conversationIdentifier = window.currentViewedConversation.id;
    const platformType = window.currentViewedConversation.platform;

    // --- Logique pour définir les actions des boutons ---

    // Action si "Envoyer comme Assistant" est cliqué
    const assistantAction = () => {
        console.log("Exécution de l'action: Envoyer comme Assistant");
        let url;
        if (platformType === 'web') {
            url = `/admin/web/conversations/${conversationIdentifier}/send`;
        } else if (platformType === 'telegram') {
            url = `/admin/telegram/conversations/${conversationIdentifier}/send`;
        } else if (platformType === 'whatsapp') {
            url = `/whatsapp/admin/whatsapp/conversations/${encodeURIComponent(conversationIdentifier)}/send`;
        } else {
            console.error(`Unsupported platform type: ${platformType}`);
            alert(`Plateforme non supportée: ${platformType}`);
            return;
        }

        fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: messageContent })
        })
        .then(response => {
            if (!response.ok) { throw new Error(`Erreur HTTP ${response.status}`); }
            return response.json();
        })
        .then(data => {
            if (data.error) { throw new Error(data.error); }
            adminMessageInput.value = ''; // Vider l'input
            if (data.message_data) {
                // Ajouter visuellement le message admin à l'interface
                appendSingleMessageToModal(data.message_data);
            }
            console.log('Admin message sent AS ASSISTANT:', data);
        })
        .catch(error => {
            console.error('Error sending admin message AS ASSISTANT:', error);
            alert(`Erreur lors de l'envoi comme Assistant: ${error.message}`);
        });
    };

    // Action si "Envoyer comme Utilisateur" est cliqué
    const userAction = () => {
        console.log("Exécution de l'action: Envoyer comme Utilisateur (Simulé)");
        if (platformType === 'whatsapp') {
            url = `/whatsapp/admin/trigger_ai_as_user/${encodeURIComponent(conversationIdentifier)}`;
        } else if (platformType === 'telegram') {
            url = `/admin/telegram/trigger_ai_as_user/${conversationIdentifier}`;
        } else {
             alert("L'envoi 'en tant qu'utilisateur' n'est supporté que pour WhatsApp et Telegram pour le moment.");
             return;
        }
        console.log(`Triggering AI as user via URL: ${url}`);

        fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: messageContent })
        })
        .then(response => {
            if (!response.ok) { throw new Error(`Erreur HTTP ${response.status}`); }
            return response.json();
        })
        .then(data => {
            if (data.error) { throw new Error(data.error); }
            adminMessageInput.value = ''; // Vider l'input
            console.log('AI triggered AS USER successfully:', data);
            showAdminNotification("Message envoyé à l'IA comme utilisateur."); // Notifier l'admin
            // La réponse de l'IA sera ajoutée via l'événement SocketIO
        })
        .catch(error => {
            console.error('Error triggering AI AS USER:', error);
            alert(`Erreur lors du déclenchement IA: ${error.message}`);
        });
    };

    // --- Appel du nouveau modal ---
    showSendAsModal(assistantAction, userAction);
}

// Fonction basique pour afficher une notification (à adapter)
function showAdminNotification(message) {
    console.log("ADMIN NOTIF:", message);
    // Idéalement, utiliser un système de "toast" non bloquant
    // alert(message); // Éviter alert si possible
}

function showSendAsModal(assistantCallback, userCallback) {
    console.log("Affichage du modal SendAs...");
    const modal = document.getElementById('sendAsModal');
    const assistantBtn = document.getElementById('sendAsAssistantBtn');
    const userBtn = document.getElementById('sendAsUserBtn');
    const closeBtn = modal.querySelector('.close-modal'); // Sélectionne le bouton de fermeture DANS ce modal

    // --- IMPORTANT : Nettoyer les anciens écouteurs pour éviter les appels multiples ---
    // La méthode la plus simple et robuste est de cloner les boutons
    const newAssistantBtn = assistantBtn.cloneNode(true);
    const newUserBtn = userBtn.cloneNode(true);
    assistantBtn.parentNode.replaceChild(newAssistantBtn, assistantBtn);
    userBtn.parentNode.replaceChild(newUserBtn, userBtn);

    // Ajouter les nouveaux écouteurs aux boutons clonés
    newAssistantBtn.addEventListener('click', () => {
        console.log("Clic sur 'Envoyer comme Assistant'");
        if (typeof assistantCallback === 'function') {
            assistantCallback(); // Exécute l'action "Assistant"
        }
        closeSendAsModal(); // Ferme le modal après action
    });

    newUserBtn.addEventListener('click', () => {
        console.log("Clic sur 'Envoyer comme Utilisateur'");
        if (typeof userCallback === 'function') {
            userCallback(); // Exécute l'action "Utilisateur"
        }
        closeSendAsModal(); // Ferme le modal après action
    });

    // Afficher le modal et l'overlay
    modal.style.display = 'block';
    // Tu peux réutiliser l'overlay existant si un seul modal est affiché à la fois
    document.body.style.overflow = 'hidden'; // Empêcher le défilement
}

function closeSendAsModal() {
    console.log("Fermeture du modal SendAs.");
    const modal = document.getElementById('sendAsModal');
    modal.style.display = 'none';
    // document.getElementById('modalOverlay').style.display = 'none'; // Cacher l'overlay si nécessaire
    document.body.style.overflow = 'auto'; // Réactiver le défilement
}

let conversationIdentifierToDelete = null;
let conversationPlatformToDelete = null;

// Accepte maintenant un objet filterParams { filter: '...', search: '...' } (notez 'filter' au lieu de 'status')
function fetchAllConversations(platform, page = 1, filterParams = {}) {
    console.log(`Workspaceing conversations for platform: ${platform}, page: ${page}, filters:`, filterParams);

    const params = new URLSearchParams({
        page: page,
        per_page: ITEMS_PER_PAGE
    });
    if (filterParams.status && filterParams.status !== 'all') {
        params.append('filter', filterParams.status); // Utilise 'filter' pour le backend
    }
    if (filterParams.search && filterParams.search.trim() !== '') {
        params.append('search', filterParams.search.trim());
    }
    const url = `/admin/conversations/${platform}?${params.toString()}`;

     // TODO: (Optionnel) Afficher indicateur chargement

    fetch(url)
        .then(response => {
             if (!response.ok) {
                  return response.json().catch(() => {
                    throw new Error(`Erreur HTTP ${response.status} (${response.statusText}) pour ${url}`);
                 }).then(errData => {
                    throw new Error(errData.error || `Erreur HTTP ${response.status}`);
                 });
             }
             currentConversationFilter = { ...filterParams }; // Mémorise filtre si succès
             return response.json();
        })
        .then(data => {
            // console.log(`Data received for ${platform} conversations page ${page} with filters:`, data);
             if (data.conversations && data.pagination) {
                 updateFullConversationsTable(data.conversations, platform);
                 conversationPagination = data.pagination;
                 currentConversationPage = data.pagination.current_page;
                 console.log('--- Pagination Conversations Reçue (fetchAllConversations) ---');
                 console.log(conversationPagination);
                 renderConversationPaginationControls(conversationPagination);

                 if(data.conversations.length === 0) {
                    showEmptyState('fullConversationsTableContainer', platform, 'conversations');
                    const emptyStateP = document.querySelector('#fullConversationsTableContainer .empty-state p');
                    if(emptyStateP) {
                        if (currentConversationFilter.status || (currentConversationFilter.search && currentConversationFilter.search.trim() !== '')) {
                            emptyStateP.textContent = "Aucune conversation ne correspond à vos critères.";
                        } else {
                            const platformName = platform === 'web' ? 'Web' : platform.charAt(0).toUpperCase() + platform.slice(1);
                            emptyStateP.textContent = `Aucune conversation ${platformName} disponible pour le moment`;
                        }
                    }
                 }
            } else {
                 console.error("Données reçues invalides du serveur:", data);
                 showEmptyState('fullConversationsTableContainer', platform, 'conversations');
                 renderConversationPaginationControls({});
            }
            // TODO: (Optionnel) Cacher indicateur chargement
        })
        .catch(error => {
            console.error(`Error fetching ${platform} conversations page ${page} with filters:`, error);
            showEmptyState('fullConversationsTableContainer', platform, 'conversations');
            conversationPagination = {};
            renderConversationPaginationControls(conversationPagination);
            const emptyStateP = document.querySelector('#fullConversationsTableContainer .empty-state p');
             if(emptyStateP) emptyStateP.textContent = `Erreur lors du chargement: ${error.message}`;
            // TODO: (Optionnel) Cacher indicateur chargement
        });
}

function renderUserPaginationControls(pagination) {
    const controlsContainer = document.getElementById('userPaginationControls');
    const prevButton = document.getElementById('userPrevPage');
    const nextButton = document.getElementById('userNextPage');
    const pageInfo = document.getElementById('userPageInfo');

    if (!pagination || !pagination.total_items || pagination.total_items === 0) {
        controlsContainer.style.display = 'none'; // Cacher si pas d'items
        return;
    }

    controlsContainer.style.display = 'block'; // Afficher les contrôles

    // Mettre à jour les infos de page
    pageInfo.textContent = `Page ${pagination.current_page} / ${pagination.total_pages}`;

    // Activer/désactiver bouton Précédent
    prevButton.disabled = !pagination.has_prev;
    // Activer/désactiver bouton Suivant
    nextButton.disabled = !pagination.has_next;
}

// Variables globales pour la pagination des abonnements (si nécessaire plus tard)
let currentSubscriptionPage = 1;
let subscriptionPagination = {};

// Fonction pour récupérer les abonnements (version basique pour état vide)
function fetchAllSubscriptions(platform, page = 1, filterParams = {}) {
    console.log(`Workspaceing subscriptions for platform: ${platform}, page: ${page}, filters:`, filterParams);

    // Construire l'URL (même si le backend n'est pas prêt, on prépare)
    const params = new URLSearchParams({
        page: page,
        per_page: ITEMS_PER_PAGE // Utiliser la même constante
    });
    // Ajouter potentiels filtres/recherche plus tard si besoin
    // if (filterParams.status && filterParams.status !== 'all') { params.append('status', filterParams.status); }
    // if (filterParams.search && filterParams.search.trim() !== '') { params.append('search', filterParams.search.trim()); }
    const url = `/admin/subscriptions/${platform}?${params.toString()}`; // <-- Nouvelle route backend (à créer !)

    // Optionnel : Afficher indicateur chargement

    fetch(url)
        .then(response => {
            // Si la route backend n'existe pas encore, ça va probablement échouer ici
            if (!response.ok) {
                 // Si erreur serveur (ex: 404 Not Found), on considère qu'il n'y a pas de données
                console.warn(`Backend route ${url} might be missing or returned error ${response.status}`);
                // On force l'affichage de l'état vide
                return { subscriptions: [], pagination: {} }; // Renvoyer structure vide
            }
            return response.json();
        })
        .then(data => {
            console.log(`Data received for ${platform} subscriptions page ${page}:`, data);

            // Vérifier si la liste est vide
            if (data.subscriptions && data.subscriptions.length > 0) {
                // --- LOGIQUE D'AFFICHAGE DU TABLEAU (à implémenter plus tard) ---
                // Exemple: updateSubscriptionsTable(data.subscriptions, platform);
                // Exemple: subscriptionPagination = data.pagination;
                // Exemple: currentSubscriptionPage = data.pagination.current_page;
                // Exemple: renderSubscriptionPaginationControls(subscriptionPagination);

                // Pour l'instant, on affiche juste l'état vide si on arrive ici par erreur
                 console.log("Received subscriptions, but display logic not implemented yet. Showing empty state for now.");
                 showEmptyState('subscriptionsTableContainer', platform, 'subscriptions');
                 renderSubscriptionPaginationControls({}); // Cacher les contrôles pagination

            } else {
                // La requête a réussi mais pas d'abonnement (ou la route n'existe pas et on a renvoyé [])
                showEmptyState('subscriptionsTableContainer', platform, 'subscriptions');
                subscriptionPagination = {}; // Réinitialiser pagination
                renderSubscriptionPaginationControls(subscriptionPagination); // Cacher/désactiver contrôles
            }
            // Optionnel : Cacher indicateur chargement
        })
        .catch(error => {
            // En cas d'erreur réseau ou autre
            console.error(`Error fetching ${platform} subscriptions page ${page}:`, error);
            showEmptyState('subscriptionsTableContainer', platform, 'subscriptions');
            subscriptionPagination = {}; // Réinitialiser pagination
            renderSubscriptionPaginationControls(subscriptionPagination); // Cacher/désactiver contrôles
             // Optionnel : Cacher indicateur chargement
        });
}

// Fonction pour afficher les contrôles de pagination des abonnements (à créer)
function renderSubscriptionPaginationControls(pagination) {
     // À implémenter si vous ajoutez la pagination pour les abonnements
     console.log("renderSubscriptionPaginationControls called with:", pagination);
}

function renderConversationPaginationControls(pagination) {
    const controlsContainer = document.getElementById('conversationPaginationControls');
    const prevButton = document.getElementById('convPrevPage');
    const nextButton = document.getElementById('convNextPage');
    const pageInfo = document.getElementById('convPageInfo');

     if (!pagination || !pagination.total_items || pagination.total_items === 0) {
        controlsContainer.style.display = 'none'; // Cacher si pas d'items
        return;
    }

    controlsContainer.style.display = 'block'; // Afficher les contrôles

    // Mettre à jour les infos de page
    pageInfo.textContent = `Page ${pagination.current_page} / ${pagination.total_pages}`;

    // Activer/désactiver bouton Précédent
    prevButton.disabled = !pagination.has_prev;
    // Activer/désactiver bouton Suivant
    nextButton.disabled = !pagination.has_next;
}

function updateFullConversationsTable(conversations, platform) {
    const tableBody = document.getElementById('fullConversationsTable').getElementsByTagName('tbody')[0];
    const tableElement = document.getElementById('fullConversationsTable');
    const container = document.getElementById('fullConversationsTableContainer');
    const emptyState = container.querySelector('.empty-state');

    // Vider le contenu précédent du tableau !
    tableBody.innerHTML = '';

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

        const conversationTitle = conversation.title || 'Sans titre';

        // --- NOUVEAU : Déterminer l'identifiant et le type pour le bouton "Voir" ---
        let viewIdentifier;
        let platformType = platform; // Garde la plateforme actuelle ('web', 'telegram', 'whatsapp')
        let viewIdentifierForDisplay; // Pour le onclick

        if (platform === 'whatsapp') {
            // Pour WhatsApp, l'ID est le thread_id (chaîne), passé tel quel.
            viewIdentifier = conversation.id; // L'API renvoie le thread_id dans le champ 'id' pour WA
            viewIdentifierForDisplay = `'${viewIdentifier}'`; // Doit être une chaîne dans l'appel onclick
        } else {
            // Pour Web/Telegram, utiliser l'ID numérique de la base de données.
            viewIdentifier = conversation.id;
            viewIdentifierForDisplay = viewIdentifier; // Est déjà un nombre
        }

        // Vérifier si l'identifiant est valide avant de créer le bouton
        const isIdentifierValid = viewIdentifier !== undefined && viewIdentifier !== null;

        row.innerHTML = `
            <td>${conversationTitle}</td>
            <td><span class="platform-badge ${platform}">${platform}</span></td>
            <td>${conversation.date || ''}</td>
            <td>${truncatedMessage}</td>
            <td><span class="status-badge ${isActive ? 'active' : 'archived'}">${isActive ? 'Active' : 'Archivée'}</span></td>
            <td class="action-buttons">
                ${isIdentifierValid ? `
                <button class="action-btn view" onclick="viewConversation(${viewIdentifierForDisplay}, '${platformType}')">
                    <i class="bi bi-eye"></i>
                </button>
                ` : `
                <button class="action-btn view" disabled title="ID de conversation invalide">
                    <i class="bi bi-eye-slash"></i>
                </button>
                `}
                <button class="action-btn delete" onclick="deleteConversation(${viewIdentifierForDisplay}, '${platformType}')">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        `;
    });

}

function filterConversations(statusFilter) { // 'statusFilter' ici correspond à data-filter="active" ou "archived"
    console.log(`Filtering conversations by status: ${statusFilter}`);
    // Mettre à jour l'état global des filtres conversation
    currentConversationFilter.status = (statusFilter === 'all') ? null : statusFilter;
    currentConversationFilter.search = null; // Réinitialiser la recherche

    // Réinitialiser visuellement la barre de recherche
    document.getElementById('conversationSearchInput').value = '';

     // Mettre à jour l'état actif des boutons de filtre DANS LA SECTION CONVO
     document.querySelectorAll('#conversations-section .filter-buttons .filter-btn').forEach(btn => {
         btn.classList.toggle('active', btn.getAttribute('data-filter') === statusFilter);
    });

    // Appeler fetchAllConversations avec le nouveau filtre, page 1
    fetchAllConversations(currentPlatform, 1, currentConversationFilter);
}

function searchConversations() {
    clearTimeout(searchDebounceTimeout);
    const searchTerm = document.getElementById('conversationSearchInput').value;

    searchDebounceTimeout = setTimeout(() => {
         console.log(`Searching conversations with term: "${searchTerm}"`);
        // Mettre à jour l'état global
        currentConversationFilter.search = searchTerm.trim();
        currentConversationFilter.status = null; // Réinitialiser le filtre statut

         // Réinitialiser visuellement les filtres statut (mettre 'Toutes' en actif) DANS LA SECTION CONVO
         document.querySelectorAll('#conversations-section .filter-buttons .filter-btn').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-filter') === 'all');
        });

        // Appeler fetchAllConversations avec la recherche, page 1
        fetchAllConversations(currentPlatform, 1, currentConversationFilter);
    }, 500);
}

function deleteConversation(identifier, platformType) { // <<< Signature modifiée
    // Stocker l'identifiant réel et le type de plateforme
    conversationIdentifierToDelete = identifier; // <<< Utilise la nouvelle variable
    conversationPlatformToDelete = platformType;  // <<< Utilise la nouvelle variable

    console.log(`Preparing to delete conversation for platform [${platformType}] with identifier:`, identifier); // Log utile

    // Afficher le modal de confirmation
    const modal = document.getElementById('deleteConversationModal');
    if (modal) { // Vérifier si le modal existe
        modal.style.display = 'block';
        document.body.style.overflow = 'hidden';
    } else {
        console.error("Delete confirmation modal not found!");
    }
}

function closeDeleteConversationModal() {
    const modal = document.getElementById('deleteConversationModal');
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
    conversationIdToDelete = null;
}

function confirmDeleteConversation() {
    // Utiliser les nouvelles variables globales
    if (conversationIdentifierToDelete === null || conversationPlatformToDelete === null) {
        console.error("Missing identifier or platform type for deletion.");
        closeDeleteConversationModal(); // Fermer le modal en cas d'erreur interne
        return;
    }

    let deleteUrl;

    // --- NOUVEAU : Construire l'URL de suppression basée sur la plateforme ---
    if (conversationPlatformToDelete === 'whatsapp') {
        // WhatsApp : Utiliser une route spécifique qui prend le thread_id (chaîne)
        // Supposons une route comme /admin/whatsapp/thread/<thread_id> (à créer/vérifier côté backend)
        deleteUrl = `/admin/whatsapp/thread/${encodeURIComponent(conversationIdentifierToDelete)}`;
        console.log("Using WhatsApp DELETE URL:", deleteUrl);
    } else if (conversationPlatformToDelete === 'web' || conversationPlatformToDelete === 'telegram') {
        // Web/Telegram : Utiliser une NOUVELLE route qui prend l'ID numérique
        deleteUrl = `/admin/conversations/${conversationIdentifierToDelete}`; // <<< NOUVELLE ROUTE DELETE par ID
        console.log("Using Web/Telegram DELETE URL by ID:", deleteUrl);
    } else {
        console.error(`Unsupported platform type for deletion: ${conversationPlatformToDelete}`);
        alert(`Erreur: Le type de plateforme '${conversationPlatformToDelete}' n'est pas supporté pour la suppression.`);
        closeDeleteConversationModal();
        return;
    }

    // --- MODIFIÉ : Appel fetch avec la nouvelle URL ---
    fetch(deleteUrl, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
            // Ajouter d'autres headers si nécessaire (ex: CSRF token)
        }
    })
    .then(response => {
         // Gérer les réponses non-OK de manière plus détaillée
         if (!response.ok) {
             return response.json().catch(() => {
                 // Si le corps d'erreur n'est pas JSON
                 throw new Error(`Erreur HTTP ${response.status} (${response.statusText})`);
             }).then(errorData => {
                 // Si on a un JSON d'erreur
                 throw new Error(errorData.message || errorData.error || `Erreur HTTP ${response.status}`);
             });
         }
         return response.json(); // La réponse devrait contenir { success: true, message: "..." }
    })
    .then(data => {
         if (!data.success) {
             // Gérer les cas où le backend renvoie success: false
             throw new Error(data.message || "La suppression a échoué côté serveur.");
         }
        console.log(data.message); // Log succès
        closeDeleteConversationModal();
        // Rafraîchir la page ACTUELLE des conversations, en gardant les filtres
        fetchAllConversations(currentPlatform, currentConversationPage, currentConversationFilter);
    })
    .catch(error => {
        console.error('Erreur lors de la suppression:', error);
        alert(`Erreur lors de la suppression : ${error.message}`);
        closeDeleteConversationModal();
    });
}

// Update the initialization code to include conversation handlers
document.addEventListener('DOMContentLoaded', function() {
    initializeNavigation();
    showSection('dashboard');
    fetchPlatformData('web');

    // Initialize admin message functionality
    const sendAdminMessageBtn = document.getElementById('sendAdminMessageBtn');
    if (sendAdminMessageBtn) {
        sendAdminMessageBtn.addEventListener('click', sendAdminMessage);
    }

    // Add event listener for pressing enter in the admin message input
    const adminMessageInput = document.getElementById('adminMessageInput');
    if (adminMessageInput) {
        adminMessageInput.addEventListener('keydown', function(event) {
            // Send message on Enter key (without Shift for new line)
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault(); // Prevent the default action (new line)
                sendAdminMessage();
            }
        });
    }

    // Filtres Utilisateur
    document.querySelectorAll('#users-section .filter-buttons .filter-btn').forEach(btn => {
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

    // Recherche Utilisateur (sur 'input' pour chercher pendant la frappe avec debounce)
    document.getElementById('userSearchInput').addEventListener('input', searchUsers);

    // Filtres Conversation
    document.querySelectorAll('#conversations-section .filter-buttons .filter-btn').forEach(btn => {
        btn.addEventListener('click', () => filterConversations(btn.getAttribute('data-filter')));
    });

    // Recherche Conversation
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

    // Utilisateurs
    document.getElementById('userPrevPage').addEventListener('click', () => {
        if (userPagination.has_prev) {
            // Passer les filtres actuels lors du changement de page
            fetchAllUsers(currentPlatform, userPagination.prev_page_num, currentUserFilter);
        }
    });
    document.getElementById('userNextPage').addEventListener('click', () => {
        if (userPagination.has_next) {
             // Passer les filtres actuels lors du changement de page
            fetchAllUsers(currentPlatform, userPagination.next_page_num, currentUserFilter);
        }
    });

    // Conversations
    document.getElementById('convPrevPage').addEventListener('click', () => {
        if (conversationPagination.has_prev) {
             // Passer les filtres actuels lors du changement de page
            fetchAllConversations(currentPlatform, conversationPagination.prev_page_num, currentConversationFilter);
        }
    });
    document.getElementById('convNextPage').addEventListener('click', () => {
        if (conversationPagination.has_next) {
             // Passer les filtres actuels lors du changement de page
            fetchAllConversations(currentPlatform, conversationPagination.next_page_num, currentConversationFilter);
        }
    });

    // Ajout pour fermer le modal sendAs
    const sendAsModal = document.getElementById('sendAsModal');
    const sendAsCloseBtn = sendAsModal.querySelector('.close-modal');
    if (sendAsCloseBtn) {
        sendAsCloseBtn.addEventListener('click', closeSendAsModal);
    }
    // Fermer si on clique en dehors (sur l'overlay par exemple)
    window.addEventListener('click', function(event) {
        if (event.target === sendAsModal) { // Si on clique directement sur le fond du modal (pas son contenu)
           closeSendAsModal();
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
            showNotification('Les paramètres ont été sauvegardés avec succès', 'success');
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

            // --- AJOUT DE L'ÉCOUTEUR POUR LES MESSAGES IA DÉCLENCHÉS ---
            socketInstance.on('new_admin_message', function(messageData) {
                console.log('Socket.IO received new_admin_message:', messageData);

                // Vérifier si le message concerne la conversation actuellement ouverte dans le modal
                if (window.currentViewedConversation &&
                    messageData.platform === window.currentViewedConversation.platform &&
                    messageData.conversation_identifier === window.currentViewedConversation.id) {

                    console.log("Message is for the currently viewed conversation. Appending to UI.");

                    // Utiliser une fonction pour ajouter le message à l'UI du modal
                    // (Cette fonction existe peut-être déjà ou tu peux l'adapter de displayConversationMessages)
                    appendSingleMessageToModal(messageData);

                } else {
                    console.log("Message is not for the currently viewed conversation.");
                    // Optionnel : Afficher une notification générique qu'un message a été envoyé
                    // dans une autre conversation si tu le souhaites.
                }
            });

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

            console.log('Socket.IO initialisé avec succès pour les mises à jour en temps réel');
        }
    } else {
        console.error("Socket.IO n'est pas disponible. Vérifiez que la bibliothèque est bien chargée.");
    }
}

// --- NOUVELLE FONCTION (ou adaptation) POUR AJOUTER UN SEUL MESSAGE AU MODAL ---
function appendSingleMessageToModal(message) {
    const messagesContainer = document.querySelector('#viewConversationModal .chat-messages');
    if (!messagesContainer) return; // Quitter si le modal n'est pas visible/trouvé

    const messageElement = document.createElement('div');
    // Utiliser le rôle reçu ('assistant' dans ce cas)
    messageElement.className = `message ${message.role}`;

    const contentElement = document.createElement('div');
    contentElement.className = 'message-content';

    // Gérer image si nécessaire (même si peu probable pour réponse IA texte)
    if (message.image_url) {
        const img = document.createElement('img');
        img.src = message.image_url;
        img.style.maxWidth = '200px';
        img.style.borderRadius = '4px';
        img.style.marginBottom = '8px';
        contentElement.appendChild(img);
    }

    // Ajouter le texte (plus sûr avec textContent ou une fonction d'échappement)
    // Pour l'instant, on garde innerHTML mais attention si le contenu peut venir d'ailleurs
    contentElement.innerHTML += message.content;
    messageElement.appendChild(contentElement);
    messagesContainer.appendChild(messageElement);

    // Faire défiler vers le nouveau message
    const viewport = document.querySelector('#viewConversationModal .chat-viewport');
    if (viewport) {
        viewport.scrollTop = viewport.scrollHeight;
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