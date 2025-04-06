# Fonction utilitaire pour récupérer les messages stockés en session si nécessaire
@app.route('/api/recover_message/<int:message_id>', methods=['GET'])
def recover_message(message_id):
    """Endpoint pour récupérer un message qui n'a pas pu être sauvegardé en BD ou dont le streaming s'est interrompu"""
    try:
        # D'abord, vérifier dans la base de données
        message = Message.query.get(message_id)
        
        # Si le message existe et a du contenu en BD
        if message and message.content and message.content.strip():
            logger.info(f"Récupération du message {message_id} depuis la BD")
            return jsonify({'success': True, 'content': message.content})
            
        # Sinon, vérifier dans la session
        if 'message_recovery' in session and str(message_id) in session['message_recovery']:
            content = session['message_recovery'][str(message_id)]
            
            # Si le message existe en BD mais est vide, le mettre à jour
            if message and (not message.content or message.content.strip() == ''):
                try:
                    message.content = content
                    db.session.commit()
                    # Si succès, supprimer de la session
                    del session['message_recovery'][str(message_id)]
                    logger.info(f"Message {message_id} récupéré de la session et sauvegardé en BD")
                except Exception as e:
                    logger.error(f"Échec de mise à jour du message {message_id} en BD: {str(e)}")
            
            return jsonify({'success': True, 'content': content})
            
        # Message non trouvé
        logger.warning(f"Message {message_id} non trouvé ni en BD ni en session")
        return jsonify({'success': False, 'error': 'Message non trouvé'})
            
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du message {message_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})
