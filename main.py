import os
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime

from database import db, create_document, get_documents
from schemas import User, Product, Category, Review, CartItem, Order

app = FastAPI(title="E-Commerce API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc["id"] = str(doc.pop("_id")) if doc.get("_id") else None
    # Convert datetime to isoformat
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc

@app.get("/")
def read_root():
    return {"message": "E-Commerce Backend Ready"}

@app.get("/schema")
def get_schema():
    """Expose basic schema info for the database viewer."""
    return {
        "collections": [
            "user", "category", "product", "review", "cartitem", "order"
        ]
    }

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected & Working"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()[:10]
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# Auth (basic demo: not secure, no tokens)
class RegisterIn(BaseModel):
    name: str
    email: str
    password: str

@app.post("/auth/register")
def register(payload: RegisterIn):
    existing = db["user"].find_one({"email": payload.email}) if db else None
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(name=payload.name, email=payload.email, password_hash=payload.password)
    user_id = create_document("user", user)
    return {"id": user_id, "name": user.name, "email": user.email, "role": user.role}

class LoginIn(BaseModel):
    email: str
    password: str

@app.post("/auth/login")
def login(payload: LoginIn):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    user = db["user"].find_one({"email": payload.email, "password_hash": payload.password})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = serialize_doc(user)
    return {"id": user["id"], "name": user.get("name"), "email": user.get("email"), "role": user.get("role", "user")}

# Categories
@app.get("/categories")
def list_categories():
    items = [serialize_doc(x) for x in db["category"].find()] if db else []
    return items

@app.post("/categories")
def create_category(cat: Category):
    cat_id = create_document("category", cat)
    return {"id": cat_id}

# Products
@app.get("/products")
def list_products(
    q: Optional[str] = None,
    category: Optional[str] = None,
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    sort: Optional[str] = Query("-created_at"),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=60),
):
    if db is None:
        return {"items": [], "total": 0, "page": page, "pages": 0}
    filt: Dict[str, Any] = {}
    if q:
        filt["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
        ]
    if category:
        filt["category"] = category
    if min_price is not None or max_price is not None:
        pr = {}
        if min_price is not None:
            pr["$gte"] = min_price
        if max_price is not None:
            pr["$lte"] = max_price
        filt["price"] = pr

    cursor = db["product"].find(filt)
    if sort:
        direction = -1 if sort.startswith("-") else 1
        key = sort[1:] if sort.startswith("-") else sort
        cursor = cursor.sort(key, direction)
    total = cursor.count() if hasattr(cursor, 'count') else db["product"].count_documents(filt)
    cursor = cursor.skip((page - 1) * limit).limit(limit)
    items = [serialize_doc(x) for x in cursor]
    return {"items": items, "total": total, "page": page, "pages": (total + limit - 1) // limit}

@app.post("/products")
def create_product(prod: Product):
    prod_id = create_document("product", prod)
    return {"id": prod_id}

@app.get("/products/{product_id}")
def get_product(product_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    item = db["product"].find_one({"_id": ObjectId(product_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    return serialize_doc(item)

# Reviews
@app.get("/products/{product_id}/reviews")
def product_reviews(product_id: str):
    items = [serialize_doc(x) for x in db["review"].find({"product_id": product_id})] if db else []
    return items

@app.post("/products/{product_id}/reviews")
def add_review(product_id: str, rev: Review):
    data = rev.model_dump()
    data["product_id"] = product_id
    data["created_at"] = datetime.utcnow()
    _id = db["review"].insert_one(data).inserted_id
    return {"id": str(_id)}

# Cart
@app.get("/cart")
def get_cart(client_id: str = Query(...)):
    if db is None:
        return []
    pipeline = [
        {"$match": {"client_id": client_id}},
        {"$lookup": {"from": "product", "localField": "product_id", "foreignField": "_id", "as": "product"}},
        {"$unwind": "$product"}
    ]
    # Because product_id stored as string; ensure lookup works by converting to ObjectId on the fly is complex.
    # Instead, fetch items then attach product manually.
    items = list(db["cartitem"].find({"client_id": client_id}))
    result = []
    for it in items:
        prod = db["product"].find_one({"_id": ObjectId(it.get("product_id"))}) if it.get("product_id") else None
        it = serialize_doc(it)
        it["product"] = serialize_doc(prod) if prod else None
        result.append(it)
    return result

@app.post("/cart")
def add_to_cart(item: CartItem):
    data = item.model_dump()
    _id = db["cartitem"].insert_one(data).inserted_id
    return {"id": str(_id)}

class CartUpdate(BaseModel):
    qty: int

@app.patch("/cart/{item_id}")
def update_cart(item_id: str, payload: CartUpdate):
    res = db["cartitem"].update_one({"_id": ObjectId(item_id)}, {"$set": {"qty": payload.qty, "updated_at": datetime.utcnow()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Cart item not found")
    return {"ok": True}

@app.delete("/cart/{item_id}")
def remove_cart(item_id: str):
    db["cartitem"].delete_one({"_id": ObjectId(item_id)})
    return {"ok": True}

# Orders
@app.post("/orders")
def create_order(order: Order):
    data = order.model_dump()
    data["created_at"] = datetime.utcnow()
    _id = db["order"].insert_one(data).inserted_id
    return {"id": str(_id)}

@app.get("/orders")
def list_orders(client_id: Optional[str] = None):
    filt = {"client_id": client_id} if client_id else {}
    items = [serialize_doc(x) for x in db["order"].find(filt).sort("created_at", -1)] if db else []
    return items

# Seed demo data if database empty
@app.post("/seed")
def seed_data():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    if db["product"].count_documents({}) > 0:
        return {"ok": True, "message": "Already seeded"}
    categories = [
        {"name": "Cards", "slug": "cards", "icon": "CreditCard", "description": "Payment cards and fintech"},
        {"name": "Accessories", "slug": "accessories", "icon": "Star", "description": "Premium accessories"},
        {"name": "Software", "slug": "software", "icon": "Settings", "description": "Apps and tools"},
    ]
    db["category"].insert_many(categories)
    products = []
    for i in range(1, 25):
        products.append({
            "title": f"Premium Card {i}",
            "description": "Elegant glassmorphic fintech card with premium perks.",
            "price": 49.0 + i,
            "category": "cards",
            "images": [
                "https://images.unsplash.com/photo-1633265486064-086b219478d0?q=80&w=1200&auto=format&fit=crop",
                "https://images.unsplash.com/photo-1563013544-824ae1b704d3?q=80&w=1200&auto=format&fit=crop"
            ],
            "rating": 4.5,
            "rating_count": 120 + i,
            "in_stock": True,
            "features": ["Metal body", "Cashback", "Priority support"]
        })
    db["product"].insert_many(products)
    return {"ok": True, "inserted": len(products)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
