const axios = require('axios');
const fs = require('node:fs');
const path = require('node:path');
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

    // Sanitize user-controlled output to prevent CWE-117 log injection
    const cleanOutput = JSON.stringify(response.data).replace(/[\r\n]/g, '');
    console.log('Gemini OCR Backend Response: ' + cleanOutput);

  } catch (error) {
    const cleanErrorMsg = error.message.replace(/[\r\n]/g, '');
    console.error('Error calling extract-ocr endpoint: ' + cleanErrorMsg);
    if (error.response) {
      console.error('Status Code: ' + error.response.status);
      const cleanErrorData = JSON.stringify(error.response.data).replace(/[\r\n]/g, '');
      console.error('Data: ' + cleanErrorData);
    }
  }
}

runOCRTest();
