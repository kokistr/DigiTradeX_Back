from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, DateTime, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base

class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True)
    user_name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="user")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    purchase_orders = relationship("PurchaseOrder", back_populates="user")
    ocr_results = relationship("OCRResult", back_populates="user")

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    po_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    user_name = Column(String(100))
    po_no = Column(String(100), nullable=False, index=True)
    currency_code = Column(String(10))
    total_price = Column(String(50))
    payment_condition = Column(String(100))
    shipping_term = Column(String(100))
    discharge_port = Column(String(100))
    status = Column(String(50), default="手配中")
    cut_off_date = Column(String(50))
    etd = Column(String(50))
    eta = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user = relationship("User", back_populates="purchase_orders")
    order_items = relationship("OrderItem", back_populates="purchase_order", cascade="all, delete-orphan")
    shipping_schedules = relationship("ShippingSchedule", back_populates="purchase_order", cascade="all, delete-orphan")
    inputs = relationship("Input", back_populates="purchase_order", cascade="all, delete-orphan")
    ocr_results = relationship("OCRResult", back_populates="purchase_order", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"

    item_id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.po_id"))
    product_name = Column(String(200), nullable=False)
    quantity = Column(String(50))
    unit_price = Column(String(50))
    subtotal = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    purchase_order = relationship("PurchaseOrder", back_populates="order_items")

class ShippingSchedule(Base):
    __tablename__ = "shipping_schedules"

    shipping_id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.po_id"))
    shipping_company = Column(String(100))
    transit_point = Column(String(100))
    cut_off_date = Column(String(50))
    etd = Column(String(50))
    eta = Column(String(50))
    booking_number = Column(String(100))
    vessel_name = Column(String(100))
    voyage_number = Column(String(50))
    container_size = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    purchase_order = relationship("PurchaseOrder", back_populates="shipping_schedules")

class OCRResult(Base):
    __tablename__ = "ocr_results"

    ocr_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    po_id = Column(Integer, ForeignKey("purchase_orders.po_id"), nullable=True)
    file_path = Column(String(255), nullable=False)
    raw_text = Column(Text)
    processed_data = Column(Text)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user = relationship("User", back_populates="ocr_results")
    purchase_order = relationship("PurchaseOrder", back_populates="ocr_results")

class Input(Base):
    __tablename__ = "inputs"

    input_id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.po_id"))
    shipment_arrangement = Column(String(50))
    po_acquisition_date = Column(String(50))
    organization = Column(String(100))
    invoice_number = Column(String(100))
    payment_status = Column(String(50))
    booking_number = Column(String(100))
    memo = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    purchase_order = relationship("PurchaseOrder", back_populates="inputs")
