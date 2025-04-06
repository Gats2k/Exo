// Fonction pour vérifier et récupérer les messages dont le streaming s'est arrêté
function checkStalledStream(messageId) {
    const streamInfo = activeStreamMessages[messageId];
    
    // Si le message n'est plus en mode streaming, ne rien faire
    if (!streamInfo) {
        return;
    }
    
    console.log(`Attempting to recover stalled message ${messageId}`);
    
    // Récupérer le message complet depuis le serveur
    fetch(`/api/recover_message/${messageId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.content) {
                // Vérifier si le contenu récupéré est différent de ce que nous avons déjà
                if (data.content !== streamInfo.content) {
                    // Mettre à jour le contenu avec la réponse complète
                    streamInfo.content = data.content;
                    streamInfo.element.innerHTML = data.content.replace(/\n/g, '<br>');
                    console.log(`Stalled message ${messageId} recovered successfully`);
                    
                    // Ajouter une classe pour indiquer que le message a été récupéré
                    streamInfo.element.closest('.message').classList.add('recovered');
                }
            }
            
            // Même si on n'a pas récupéré de contenu, considérer le streaming comme terminé
            // pour éviter que le message reste en état de chargement indéfiniment
            delete activeStreamMessages[messageId];
        })
        .catch(error => {
            console.error(`Failed to recover stalled message ${messageId}:`, error);
            
            // En cas d'échec, quand même terminer le streaming pour ne pas bloquer l'interface
            delete activeStreamMessages[messageId];
            
            // Ajouter une indication visuelle que le message est incomplet
            streamInfo.element.closest('.message').classList.add('incomplete');
            streamInfo.element.innerHTML += '<div class="error-notice">⚠️ Message incomplet, actualisez la page pour réessayer</div>';
        });
}
