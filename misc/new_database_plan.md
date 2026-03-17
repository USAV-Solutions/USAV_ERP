the database schema is as follows: product_family (id, base_name) -> product_identity (id, family_code, identity_name, type, upis_h) -> product_variant (id, identity_id, color_code, condition_code, full sku).
UPIS-H is derived from the family id. add a column in product family that is family_code, auto generated, if id is 1, family code is 00001.

each product will have a product_identity which is the group name of the product. And for each product_identity, a default product variant with no color and no condition should be created with name {group name} and SKU = the UPIS-H = family_code. when creating a variant of a product with a color code or condition Code, name it {group name} {color name} {condition name}, with SKU = {UPIS-H}-{Color Code}-{Condition Code}. If color code and/or condition code is empty, just leave it empty, dont default.

parts identity should have the name {group-name} - {Component Type}, with UPIS-H = {family_code}-P-{LCI}. part variant should be named {group-name} - {Component Type} {color name} {condition name} with SKU = {UPIS-H}-{color code}-{condition code}. If color code and/or condition code is empty, just leave it empty, dont default.

Create all products and their parts first. only then, will we move on to the bundles.

Bundle should contains the items inside it (via bundle_child_component table). Bundle SKU should just be 0xxxx-B (with 0xxxx be a completely new family). Bundle name should be {first component} with {second component}. each bundle should standalone in its family, and identity, with family name = Identity name = variant name = bundle name. UPIS-H = Full_SKU = 0xxxx-B. if bundle has a Color or condition field, assign that to the sku of the first component in the component list. before creating the bundle, check if the components with that name already exist or not, if not, create. Check components by checking these 3 naming convention in product_identity and product_variants sequentially, if one of those exist, take it, else, create: {component name}, {group name} - {component name}. if the bundle has color or condition field, then continue checking the variant for the first component of the component list for the variant of that color, with SKU beginning with {product_identity}-{color code given}. if the component has not to exist, check if the component name contains the group name. if yes, create it with name {component name}. if no, create it with name {group name} - {component name}. sku of newly created component should be linked to the group sku. 

here are some color codes and condition codes in the excel sheet, colors in the db is enum type, you can run docker exec to check.

GR - Graphite
CH - Cherry
BK - Black
WH - White
GY - Grey
PL - Platinum White
CR - Cream


N - New
R - Refurbished
U - Used