from fastapi import FastAPI, HTTPException, Depends, Header, Form, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
import base64
import hashlib
import time
import mysql.connector
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# authorization key
SECRET_KEY = "4rb4Tr4v3l123"

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)  #Debug for upload directory to exist

# store picture
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

class User(BaseModel):
    name: str
    email: str
    password: str

class Comment(BaseModel):
    post_id: int
    comment: str

class CommentRequest(BaseModel):
    post_id: int

class LoginRequest(BaseModel):
    email: str
    password: str

def get_db_connection():
    conn = mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="test_db"
    )
    return conn

@app.post("/users/login")
def login_user(user: LoginRequest):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Verify if the user exists
        cursor.execute("SELECT * FROM users WHERE email = %s", (user.email,))
        user_data = cursor.fetchone()

        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        # Validate the password
        hashed_password = hashlib.sha256(user.password.encode()).hexdigest()
        if hashed_password != user_data["password"]:
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        # Generate the token
        timestamp = str(int(time.time()))
        raw_token = f"{user.email}:{timestamp}:{SECRET_KEY}"
        token = base64.b64encode(raw_token.encode()).decode()

        return {"message": "Login successful!", "token": token, "user_id": user_data["id"]}

    except Exception as e:
        raise HTTPException(status_code=500, detail="An error occurred during login.")
    
    finally:
        cursor.close()
        conn.close()

@app.post("/users/register")
def create_user(user: User):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE email = %s", (user.email,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="Email already exists")

    hashed_password = hashlib.sha256(user.password.encode()).hexdigest()
    cursor.execute("INSERT INTO users (name, email, password) VALUES (%s, %s, %s)",
                   (user.name, user.email, hashed_password))
    conn.commit()

    user_id = cursor.lastrowid
    timestamp = str(int(time.time()))
    raw_token = f"{user.email}:{timestamp}:{SECRET_KEY}"
    token = base64.b64encode(raw_token.encode()).decode()

    cursor.close()
    conn.close()
    return {"message": "User created successfully!", "token": token, "user_id": user_id}

def verify_token(authorization: str = Header(None)):
    if not authorization:
        print("Authorization header is missing.")  # Log the missing header
        raise HTTPException(status_code=401, detail="Authorization header missing")

    try:
        decoded_token = base64.b64decode(authorization).decode()
        print("Decoded token:", decoded_token)  # Print the decoded token for debugging
        email, timestamp, secret = decoded_token.split(":")
        if secret != SECRET_KEY:
            raise HTTPException(status_code=401, detail="Invalid token")
        if time.time() - int(timestamp) > 10600:
            raise HTTPException(status_code=401, detail="Token expired")
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user["id"]
    except Exception as e:
        print(f"Error decoding token: {e}")
        raise HTTPException(status_code=401, detail="Invalid token format")

@app.post("/post/upload")
async def create_post(
    caption: str = Form(...),
    photo: UploadFile = None,  # Allow photo to be None
    user_id: int = Depends(verify_token)
):
    if not caption:
        raise HTTPException(status_code=400, detail="Caption is required.")

    file_path = None
    if photo:
        # Proceed if photo is provided
        file_path = os.path.join(UPLOAD_DIR, photo.filename)
        with open(file_path, "wb") as f:
            f.write(await photo.read())

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO posts (user_id, image, caption) VALUES (%s, %s, %s)",
        (user_id, file_path, caption)
    )
    conn.commit()

    post_id = cursor.lastrowid

    cursor.close()
    conn.close()

    return JSONResponse(content={"message": "Post created successfully!", "post_id": post_id})

# Utility function to convert datetime to string
def convert_datetime(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()  # Convert to ISO format string
    raise TypeError(f"Type {type(obj)} not serializable")

from fastapi import FastAPI, Request

@app.get("/post/list")
async def list_post(request: Request, user_id: int = Depends(verify_token)):  # Check authentication token
    # Get the base URL dynamically from the request
    base_url = str(request.base_url)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)  # Ensure dictionary format for posts
    
    try:
        cursor.execute("SELECT posts.*, users.name FROM `posts` LEFT JOIN users ON posts.user_id = users.id ORDER BY date_created DESC")
        posts = cursor.fetchall()

        for post in posts:
            post['date_created'] = convert_datetime(post['date_created'])

            # Add the full URL for the image
            if post['image']:
                post['image'] = f"{base_url}{post['image']}"

        cursor.close()
        conn.close()

        return JSONResponse(content={"message": "Posts retrieved successfully!", "posts": posts})

    except Exception as e:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=500, detail="An error occurred while retrieving posts.")

    
@app.post("/post/delete")
async def delete_post(post_data: dict, user_id: int = Depends(verify_token)):  # Receive post data and authenticated user ID
    post_id = post_data.get("post_id")

    if not post_id:
        raise HTTPException(status_code=400, detail="Post ID is required.")

    # Check if the post exists and belongs to the user
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
    post = cursor.fetchone()

    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    
    if post["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to delete this post.")

    # Delete the post
    cursor.execute("DELETE FROM posts WHERE id = %s", (post_id,))
    conn.commit()

    cursor.close()
    conn.close()

    return JSONResponse(content={"message": "Post deleted successfully!"})

@app.post("/post/comment")
async def comment_post(comment_data: Comment, user_id: int = Depends(verify_token)):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Insert the comment into the database
    try:
        cursor.execute(
            "INSERT INTO comments (post_id, user_id, text) VALUES (%s, %s, %s)",
            (comment_data.post_id, user_id, comment_data.comment)
        )
        conn.commit()
        comment_id = cursor.lastrowid
        cursor.close()
        conn.close()

        return JSONResponse(content={"message": "Comment posted successfully!", "comment_id": comment_id})
    except Exception as e:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=500, detail="An error occurred while posting the comment.")
    
from fastapi import FastAPI, HTTPException, Depends, Query

@app.get("/comment/list")
async def get_comments(post_id: int = Query(...), user_id: int = Depends(verify_token)):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Fetch comments for the specified post
        cursor.execute(
            "SELECT comments.*,users.name FROM comments LEFT JOIN users ON comments.user_id=users.id WHERE post_id=%s ORDER BY created_at DESC", 
            (post_id,)
        )
        comments = cursor.fetchall()
        
        # Convert timestamp to ISO 8601 format
        for comment in comments:
            comment['created_at'] = convert_datetime(comment['created_at'])

        cursor.close()
        conn.close()

        return JSONResponse(content={"message": "Comments retrieved successfully!", "comments": comments})
    except Exception as e:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=500, detail="An error occurred while retrieving comments.")
    
@app.post("/comment/delete")
async def delete_post(comment_data: dict, user_id: int = Depends(verify_token)):  # Receive post data and authenticated user ID
    comment_id = comment_data.get("comment_id")

    if not comment_id:
        raise HTTPException(status_code=400, detail="Comment ID is required.")

    # Check if the post exists and belongs to the user
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM comments WHERE id = %s", (comment_id,))
    post = cursor.fetchone()

    if not post:
        raise HTTPException(status_code=404, detail="Comment not found.")
    
    if post["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to delete this comment.")

    # Delete the post
    cursor.execute("DELETE FROM comments WHERE id = %s", (comment_id,))
    conn.commit()

    cursor.close()
    conn.close()

    return JSONResponse(content={"message": "Comment deleted successfully!"})






