import geopandas as gpd
from shapely.geometry import Point
import requests
from zipfile import ZipFile, BadZipFile
from io import BytesIO
import os
import tempfile
from pyproj import Transformer

def latlon_to_web_mercator(lat, lon):
    transformer = Transformer.from_crs("epsg:4326", "epsg:3857", always_xy=True)
    x, y = transformer.transform(lon, lat)
    return x, y

# HUC6 or 8 from ArcGIS
def query_watershed(gps_coordinate, loc):
    try:
        lon, lat = gps_coordinate
        x, y = latlon_to_web_mercator(lat, lon)
        # Map loc to layer ID based on HUC level: e.g., '3' for HUC6, '4' for HUC8
        layer_id = '3' if loc == 'huc6' else '4' if loc == 'huc8' else '3'
        url = f"https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/{layer_id}/query"
        params = {
            'where': "1=1",
            'geometry': f"{x},{y}",
            'geometryType': 'esriGeometryPoint',
            'inSR': '102100',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': f"name,{loc}",  # Dynamic field names based on HUC level
            'returnGeometry': 'false',
            'f': 'json'
        }
        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        if 'features' in data and len(data['features']) > 0:
            attributes = data['features'][0].get('attributes', {})
            watershed_name = attributes.get('name')  # The name of the watershed
            watershed_code = attributes.get(loc)  # Dynamic HUC code based on loc
            if watershed_name and watershed_code:
                return watershed_name, watershed_code
            else:
                print(f"Name or {loc.upper()} not found in the attributes.")
                return None, None
        else:
            print("No features found at this location.")
            return None, None

    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None, None

def find_watershed(gps_coordinate, shapefile_path):
    # Load the shapefile using geopandas
    watersheds = gpd.read_file(shapefile_path)

    # Create a Point object from the GPS coordinate
    point = Point(gps_coordinate)

    # Iterate through each watershed polygon and check if the point is within it
    for idx, watershed in watersheds.iterrows():
        if point.within(watershed.geometry):  # Use 'geometry' for the polygon
            return watershed  # Return the entire watershed data

    return None  # If no watershed is found
    
def get_hu_watershed(url, coords, layer, loc):
    # Send a GET request to the server
    response = requests.get(url)

    if 'application/zip' in response.headers.get('Content-Type', ''):
        try:
            with ZipFile(BytesIO(response.content)) as the_zip:                
                # Extract to a temporary directory
                with tempfile.TemporaryDirectory() as temp_dir:
                    the_zip.extractall(temp_dir)
                    print("Extracted files to:", temp_dir)

                    # Assuming the geodatabase directory's name contains 'wbdhu2_a_us_september2023.gdb'
                    gdb_dir = [d for d in os.listdir(temp_dir) if d.endswith('.gdb')]
                    if not gdb_dir:
                        print("No geodatabase directory found in the zip.")
                        return None

                    gdb_path = os.path.join(temp_dir, gdb_dir[0])
                    print("GDB Path:", gdb_path)
                    
                    gdf = gpd.read_file(gdb_path, layer=layer)
                    point = Point(coords)
                    contained_watersheds = gdf[gdf.geometry.contains(point)]
                    
                    if not contained_watersheds.empty:
                        return contained_watersheds.iloc[0]['name'], contained_watersheds.iloc[0][loc]
                    else:
                        return None

        except BadZipFile:
            print("The downloaded file is not a zip file.")
    else:
        print("Downloaded content is not a zip file.")
        return None

if __name__ == "__main__":
    # Example GPS coordinate for the SWE station (39.181624, -106.282648)
    gps_coordinate = (-105.0499163, 39.7516321)

    # Get watershed information for the GPS coordinate at different HUC levels
    hu6_result = query_watershed(gps_coordinate, 'huc6')
    hu8_result = query_watershed(gps_coordinate, 'huc8')

    # Print all results here
    for level, result in [('HU6', hu6_result), ('HU8', hu8_result)]:
        if result:
            name, code = result
            print(f"{level} found: {name} (Code: {code})")
        else:
            print(f"Error: Unable to find {level} watershed information.")