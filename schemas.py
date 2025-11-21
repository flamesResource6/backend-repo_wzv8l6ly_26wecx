"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password_hash: str = Field(..., description="Hashed password")
    address: Optional[str] = Field(None, description="Address")
    is_active: bool = Field(True, description="Whether user is active")
    role: Literal["user", "admin"] = Field("user", description="User role")

class Category(BaseModel):
    name: str
    slug: str
    icon: Optional[str] = None
    description: Optional[str] = None

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    category: str
    images: List[str] = []
    rating: float = Field(4.5, ge=0, le=5)
    rating_count: int = 0
    in_stock: bool = True
    features: List[str] = []

class Review(BaseModel):
    product_id: str
    user_name: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    created_at: Optional[datetime] = None

class CartItem(BaseModel):
    client_id: str
    product_id: str
    qty: int = Field(1, ge=1)

class Order(BaseModel):
    client_id: str
    items: List[CartItem]
    address: str
    shipping_method: str
    payment_method: str
    promo_code: Optional[str] = None
    subtotal: float
    shipping: float
    total: float
    status: Literal["pending", "paid", "shipped", "delivered", "cancelled"] = "pending"
