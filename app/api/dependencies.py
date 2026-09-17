from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.exceptions import AuthenticationError
from app.infrastructure.database import get_session
from app.infrastructure.models import Agent
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


async def get_current_agent(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Agent:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Bearer token is required")
    payload = decode_access_token(credentials.credentials, settings)
    agent = await session.get(Agent, payload["sub"])
    if not agent or not agent.is_active:
        raise AuthenticationError("Agent is inactive or does not exist")
    return agent


CurrentAgent = Annotated[Agent, Depends(get_current_agent)]
