import psycopg2
import os
from urllib.parse import urlparse
from datetime import datetime

db_url = os.getenv('DATABASE_URL')
result = urlparse(db_url)

print("=" * 60)
print("🔍 DIAGNOSTIC COMPLET DE LA BASE DE DONNÉES")
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

    # 1. Statistiques générales
    print("📊 STATISTIQUES GÉNÉRALES")
    print("-" * 60)

    cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();")
    total_connections = cursor.fetchone()[0]

    cursor.execute("SHOW max_connections;")
    max_connections = int(cursor.fetchone()[0])

    print(f"   Connexions actives     : {total_connections}")
    print(f"   Limite maximale        : {max_connections}")
    print(f"   Disponibles            : {max_connections - total_connections}")
    print(f"   Taux d'utilisation     : {(total_connections/max_connections)*100:.1f}%\n")

    # 2. Détail des connexions par application
    print("📱 CONNEXIONS PAR APPLICATION")
    print("-" * 60)

    cursor.execute("""
        SELECT 
            COALESCE(application_name, 'Non défini') as app,
            state,
            COUNT(*) as count,
            MAX(EXTRACT(EPOCH FROM (now() - state_change))) as max_idle_seconds
        FROM pg_stat_activity 
        WHERE datname = current_database()
        GROUP BY application_name, state
        ORDER BY count DESC;
    """)

    apps = cursor.fetchall()
    for app, state, count, idle in apps:
        if idle is not None:
            idle_time = f"{int(idle)}s"
        else:
            idle_time = "N/A"
        print(f"   {app[:30]:30} | {state:10} | {count:3} connexions | Inactif: {idle_time}")

    print()

    # 3. Connexions suspectes (idle trop longtemps)
    print("⚠️  CONNEXIONS SUSPECTES (idle > 5 min)")
    print("-" * 60)

    cursor.execute("""
        SELECT 
            pid,
            COALESCE(application_name, 'Non défini') as app,
            state,
            EXTRACT(EPOCH FROM (now() - state_change))/60 as idle_minutes,
            EXTRACT(EPOCH FROM (now() - backend_start))/60 as connection_age_minutes
        FROM pg_stat_activity 
        WHERE datname = current_database()
          AND state = 'idle'
          AND state_change < now() - interval '5 minutes'
        ORDER BY state_change;
    """)

    suspects = cursor.fetchall()
    if suspects:
        for pid, app, state, idle_min, age_min in suspects:
            print(f"   PID {pid:6} | {app[:25]:25} | Idle: {int(idle_min)}min | Âge: {int(age_min)}min")
    else:
        print("   ✅ Aucune connexion suspecte détectée")

    print()

    # 4. Recommandations
    print("💡 RECOMMANDATIONS")
    print("-" * 60)

    if total_connections >= max_connections * 0.8:
        print("   🔴 CRITIQUE : Utilisation > 80% - Action immédiate requise")
    elif total_connections >= max_connections * 0.6:
        print("   🟠 ATTENTION : Utilisation > 60% - Surveillance nécessaire")
    elif len(suspects) > 5:
        print("   🟡 AVERTISSEMENT : Plusieurs connexions idle - Nettoyage recommandé")
    else:
        print("   ✅ État normal - Pas d'action immédiate nécessaire")

    cursor.close()
    conn.close()

    print("\n" + "=" * 60)

except Exception as e:
    print(f"❌ ERREUR DE CONNEXION : {e}")
    print("\n⚠️  Impossible de se connecter à la base de données")
    print("   Vérifiez que DATABASE_URL est correctement défini")

print("\n")