import psycopg2
import os
from urllib.parse import urlparse
from datetime import datetime

db_url = os.getenv('DATABASE_URL')
result = urlparse(db_url)

print("=" * 60)
print("🧹 NETTOYAGE DES CONNEXIONS IDLE")
print("=" * 60)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

try:
    conn = psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
        connect_timeout=5
    )

    cursor = conn.cursor()

    # 1. Afficher ce qui sera supprimé
    print("📋 Connexions qui seront terminées :")
    print("-" * 60)

    cursor.execute("""
        SELECT 
            pid,
            COALESCE(application_name, 'Non défini') as app,
            state,
            ROUND(EXTRACT(EPOCH FROM (now() - state_change))/60) as idle_minutes
        FROM pg_stat_activity 
        WHERE datname = current_database()
          AND state = 'idle'
          AND state_change < now() - interval '10 minutes'
          AND pid <> pg_backend_pid()
        ORDER BY state_change;
    """)

    idle_connections = cursor.fetchall()

    if not idle_connections:
        print("   ✅ Aucune connexion idle > 10 min trouvée")
        cursor.close()
        conn.close()
        exit(0)

    for pid, app, state, idle_min in idle_connections:
        print(f"   PID {pid:6} | {app[:25]:25} | Idle: {int(idle_min)} minutes")

    print(f"\n📊 Total à supprimer : {len(idle_connections)} connexions")

    # 2. Demander confirmation
    response = input("\n⚠️  Voulez-vous continuer ? (oui/non) : ")

    if response.lower() not in ['oui', 'o', 'yes', 'y']:
        print("❌ Opération annulée")
        cursor.close()
        conn.close()
        exit(0)

    # 3. Terminer les connexions
    print("\n🔄 Terminaison en cours...")

    cursor.execute("""
        SELECT pg_terminate_backend(pid) 
        FROM pg_stat_activity 
        WHERE datname = current_database()
          AND state = 'idle'
          AND state_change < now() - interval '10 minutes'
          AND pid <> pg_backend_pid();
    """)

    killed_count = cursor.rowcount
    conn.commit()

    print(f"✅ {killed_count} connexions terminées avec succès")

    # 4. Vérifier l'état après nettoyage
    print("\n📊 État après nettoyage :")
    print("-" * 60)

    cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();")
    remaining = cursor.fetchone()[0]

    cursor.execute("SHOW max_connections;")
    max_conn = int(cursor.fetchone()[0])

    print(f"   Connexions actives : {remaining}")
    print(f"   Disponibles        : {max_conn - remaining}")
    print(f"   Taux d'utilisation : {(remaining/max_conn)*100:.1f}%")

    cursor.close()
    conn.close()

    print("\n" + "=" * 60)
    print("✅ Nettoyage terminé !")
    print("=" * 60)

except Exception as e:
    print(f"❌ ERREUR : {e}")

print("\n")