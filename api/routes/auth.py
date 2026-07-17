import logging

from fastapi import APIRouter, Header, HTTPException

from ..auth import create_access_token, decode_token, hash_password, verify_password
from ..metadata_storage import create_user, get_user_by_email, get_user_by_id
from ..schemas import TokenResponse, UserCreate, UserLogin, UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse)
async def signup(req: UserCreate):
    logger.info("POST /auth/signup: email=%s", req.email)
    hashed = hash_password(req.password)
    try:
        user = await create_user(req.email, hashed, req.name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    token = create_access_token(user["id"])
    return TokenResponse(
        access_token=token,
        user=UserResponse(id=user["id"], email=user["email"], name=user["name"]),
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: UserLogin):
    logger.info("POST /auth/login: email=%s", req.email)
    user = await get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user["id"])
    return TokenResponse(
        access_token=token,
        user=UserResponse(id=user["id"], email=user["email"], name=user["name"]),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(id=user["id"], email=user["email"], name=user["name"])
