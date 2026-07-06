const axios = require('axios');
const fs = require('fs');
const path = require('path');
const FormData = require('form-data');

async function runOCRTest() {
  const imagePath = path.join(__dirname, 'Test_Packing.jpg');
  console.log(`Starting Gemini Backend OCR Test on image: ${imagePath}`);
  
  try {
    if (!fs.existsSync(imagePath)) {
      console.error(`Error: Test image not found at ${imagePath}`);
      return;
    }

    const form = new FormData();
    form.append('file', fs.createReadStream(imagePath), {
      filename: 'Test_Packing.jpg',
      contentType: 'image/jpeg'
    });

    console.log('Sending upload request to http://localhost:3636/api/orders/photo-station/extract-ocr ...');
    const response = await axios.post('http://localhost:3636/api/orders/photo-station/extract-ocr', form, {
      headers: form.getHeaders()
    });

    console.log('\n--- Gemini OCR Backend Response ---');
    console.log(JSON.stringify(response.data, null, 2));
    console.log('-----------------------------------\n');

  } catch (error) {
    console.error('Error calling extract-ocr endpoint:', error.message);
    if (error.response) {
      console.error('Status:', error.response.status);
      console.error('Data:', error.response.data);
    }
  }
}

runOCRTest();
