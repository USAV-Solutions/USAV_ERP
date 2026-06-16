from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class EbayAccountResponse(BaseModel):
    id: str
    name: str
    merchant_location_key: str
    payment_policy_id: str
    return_policy_id: str
    return_policy_id_no_returns: str
    fulfillment_policy_id_light: str
    fulfillment_policy_id_heavy: str
    fulfillment_policy_id_free: str
    heavy_item_threshold_lbs: str

class EbayCategorySuggestion(BaseModel):
    category_id: str = Field(alias="categoryId")
    category_name: str = Field(alias="categoryName")
    category_tree_node_level: int = Field(alias="categoryTreeNodeLevel", default=0)
    category_tree_node_ancestors: List[Dict[str, str]] = Field(alias="categoryTreeNodeAncestors", default_factory=list)

class EbayCategoryAspectValue(BaseModel):
    value: str

class EbayCategoryAspect(BaseModel):
    name: str = Field(alias="localizedAspectName")
    aspect_constraint: Dict[str, Any] = Field(alias="aspectConstraint", default_factory=dict)
    aspect_values: List[EbayCategoryAspectValue] = Field(alias="aspectValues", default_factory=list)

class EbayCategoryCondition(BaseModel):
    condition_id: str = Field(alias="conditionId")
    condition_description: str = Field(alias="conditionDescription")

class EbayAspectValue(BaseModel):
    name: str
    values: List[str]
    required: bool = False

class EbayPublishRequest(BaseModel):
    variant_id: int
    store_id: str
    title: str
    description: str
    price: float
    quantity: int
    condition_id: str
    category_id: str
    aspects: List[EbayAspectValue]
    weight_lbs: int
    weight_oz: int
    package_length: int
    package_width: int
    package_height: int
    is_free_shipping: bool
    use_no_returns_policy: bool
    upc: Optional[str] = None
    selected_image_urls: List[str] = Field(default_factory=list)

class EbayPublishResponse(BaseModel):
    listing_id: str
    success: bool
    message: Optional[str] = None

class EbayShortenTitleRequest(BaseModel):
    title: str

class EbayShortenTitleResponse(BaseModel):
    title: str

class EbayGenerateDescriptionRequest(BaseModel):
    title: str
    condition: str
    aspects: List[EbayAspectValue]
    brand: Optional[str] = None

class EbayGenerateDescriptionResponse(BaseModel):
    description: str

class EbaySuggestDetailsRequest(BaseModel):
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None

class EbaySuggestDetailsResponse(BaseModel):
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    title: Optional[str] = None
    aspects: List[EbayAspectValue] = Field(default_factory=list)
    weight_lbs: Optional[int] = None
    weight_oz: Optional[int] = None
    package_length: Optional[int] = None
    package_width: Optional[int] = None
    package_height: Optional[int] = None
