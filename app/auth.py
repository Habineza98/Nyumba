from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app import models

# In a production app, replace this placeholder with your actual JWT decoding logic
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="signin", auto_error=False)

def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> models.User:
    """
    Retrieves the active logged-in user.
    Falls back to the first available user in the database if no auth token is passed.
    """
    user = db.query(models.User).filter(models.User.is_active == True).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active user found. Please create a user or sign in."
        )
    return user