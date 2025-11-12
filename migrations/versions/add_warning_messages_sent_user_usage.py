"""Add warning_messages_sent to UserUsage

Revision ID: add_warning_messages_sent
Revises: 
Create Date: 2025-11-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_warning_messages_sent'
down_revision = '09eeb4ff7c88'
branch_labels = None
depends_on = None


def upgrade():
    """Ajouter la colonne warning_messages_sent à la table user_usage"""
    op.add_column('user_usage', 
        sa.Column('warning_messages_sent', sa.Integer(), nullable=False, server_default='0')
    )


def downgrade():
    """Retirer la colonne warning_messages_sent de la table user_usage"""
    op.drop_column('user_usage', 'warning_messages_sent')