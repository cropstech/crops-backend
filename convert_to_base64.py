import base64

def image_to_base64(image_path, output_file):
    with open(image_path, "rb") as image_file:
        # Read the image file as binary data
        image_data = image_file.read()
        # Encode the binary data to base64
        base64_encoded = base64.b64encode(image_data).decode('utf-8')
        
        # Write the base64 string to a file
        with open(output_file, "w") as file:
            file.write(base64_encoded)

# Example usage
image_path = "/Users/gilli/Downloads/pexels-moose-photos-170195-1036623.jpg"
output_file = "base64_image.txt"
image_to_base64(image_path, output_file)
print(f"Base64 string written to {output_file}")