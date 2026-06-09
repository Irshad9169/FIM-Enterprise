#!/usr/bin/env python3
"""
Create test users with different roles
"""
import asyncio
import sys
sys.path.insert(0, '/opt/fim')

from app.core.database import get_db
from app.core.security import get_password_hash
from app.models import User
from sqlalchemy import select
import uuid

async def create_test_users():
    async for db in get_db():
        users_to_create = [
            {
                'username': 'admin',
                'email': 'admin@untd.com',
                'password': 'admin123',
                'role': 'admin',
                'full_name': 'System Administrator'
            },
            {
                'username': 'analyst1',
                'email': 'analyst1@untd.com',
                'password': 'analyst123',
                'role': 'analyst',
                'full_name': 'Senior Analyst'
            },
            {
                'username': 'trainee1',
                'email': 'trainee1@untd.com',
                'password': 'trainee123',
                'role': 'trainee',
                'full_name': 'Junior Analyst'
            },
            {
                'username': 'auditor1',
                'email': 'auditor@untd.com',
                'password': 'auditor123',
                'role': 'auditor',
                'full_name': 'Security Auditor'
            }
        ]
        
        print("Creating test users...")
        print("=" * 60)
        
        for user_data in users_to_create:
            # Check if user exists
            result = await db.execute(
                select(User).where(User.username == user_data['username'])
            )
            existing_user = result.scalar_one_or_none()
            
            if existing_user:
                # Update role if exists
                existing_user.role = user_data['role']
                existing_user.email = user_data['email']
                existing_user.full_name = user_data['full_name']
                print(f"✅ Updated: {user_data['username']} (role: {user_data['role']})")
            else:
                # Create new user
                new_user = User(
                    id=uuid.uuid4(),
                    username=user_data['username'],
                    email=user_data['email'],
                    password_hash=get_password_hash(user_data['password']),
                    role=user_data['role'],
                    full_name=user_data['full_name'],
                    is_active=True
                )
                db.add(new_user)
                print(f"✅ Created: {user_data['username']} (role: {user_data['role']})")
        
        await db.commit()
        print("=" * 60)
        print("\nTest Users Created:")
        print("-" * 60)
        print("Username    | Password    | Role     | Permissions")
        print("-" * 60)
        print("admin       | admin123    | admin    | Full access")
        print("analyst1    | analyst123  | analyst  | Generate, Review, Submit")
        print("trainee1    | trainee123  | trainee  | Review, Submit only")
        print("auditor1    | auditor123  | auditor  | Read-only, Audit logs")
        print("-" * 60)
        
        break

if __name__ == '__main__':
    asyncio.run(create_test_users())
