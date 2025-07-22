const chatBox = document.getElementById("chat-box");
const userInput = document.getElementById("user-input");
const voiceInputBtn = document.getElementById("voice-input-btn");
const ttsAudio = document.getElementById("tts-audio");
const mentalHealthModeBtn = document.getElementById("mentalHealthMode");
const studyBuddyModeBtn = document.getElementById("studyBuddyMode");

let currentChatMode = "mental_health"; // Default mode
let mediaRecorder;
let audioChunks = [];

// Function to display messages in the chat box
function displayMessage(sender, text, canSpeak = false) {
    const messageElement = document.createElement("p");
    // Sanitize text to prevent HTML injection
    const sanitizedText = text.replace(/</g, "&lt;").replace(/>/g, "&gt;");
    messageElement.innerHTML = `<strong>${sender}:</strong> ${sanitizedText}`;

    if (canSpeak && sender === "MindMate") { // Only allow speaking AI responses
        const speakIcon = document.createElement("span");
        speakIcon.innerHTML = " 🔊"; // Speaker emoji
        speakIcon.style.cursor = "pointer";
        speakIcon.title = "Listen to response";
        speakIcon.onclick = () => speakText(text);
        messageElement.appendChild(speakIcon);
    }
    chatBox.appendChild(messageElement);
    chatBox.scrollTop = chatBox.scrollHeight;
}

// Function to send an initial greeting if no history is present
async function sendInitialGreeting() {
    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "Hello MindMate, I'm here.", chat_type: currentChatMode }) // Send a dummy first message
        });
        const data = await response.json();
        displayMessage("MindMate", data.response, true);
    } catch (error) {
        console.error("Error sending initial greeting:", error);
        displayMessage("MindMate", "I'm sorry, I couldn't start our conversation. Please try refreshing the page.");
    }
}

// Load initial history when the page loads
window.onload = () => {
    // The initialHistory variable is expected to be defined in a <script> tag in index.html
    // It is populated by Flask.
    if (typeof initialHistory !== 'undefined' && initialHistory.length > 0) {
        initialHistory.forEach(msg => {
            displayMessage(msg.role === "user" ? "You" : "MindMate", msg.text, msg.role === "model");
        });
    } else {
        // If no history, send a greeting to trigger the first AI response
        sendInitialGreeting();
    }
};


// Function to send messages to the backend
async function sendMessage() {
    const userText = userInput.value.trim();

    if (userText === "") return;

    displayMessage("You", userText);
    userInput.value = "";

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userText, chat_type: currentChatMode })
        });

        if (!response.ok) {
            throw new Error(`Server responded with status: ${response.status}`);
        }

        const data = await response.json();
        displayMessage("MindMate", data.response, true);
    } catch (error) {
        console.error("Error sending message:", error);
        displayMessage("MindMate", "Sorry, I'm having trouble responding right now. Please try again.");
    }
}

// Event listener for Enter key
userInput.addEventListener("keypress", function(event) {
    if (event.key === "Enter") {
        sendMessage();
    }
});

// --- Speech-to-Text (Microphone Input) ---
voiceInputBtn.addEventListener("click", async () => {
    if (voiceInputBtn.classList.contains("recording")) {
        // Stop recording
        if (mediaRecorder && mediaRecorder.state === "recording") {
            mediaRecorder.stop();
        }
        voiceInputBtn.classList.remove("recording");
        voiceInputBtn.textContent = "🎤";
    } else {
        // Start recording
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            // --- Start of Recording Logic ---
            voiceInputBtn.classList.add("recording");
            voiceInputBtn.textContent = "🔴 Recording...";
            
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = event => {
                audioChunks.push(event.data);
            };

            mediaRecorder.onstop = async () => {
                // Stop all audio tracks to release the microphone
                stream.getTracks().forEach(track => track.stop());

                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                const formData = new FormData();
                formData.append('audio', audioBlob, 'audio.webm');

                try {
                    const response = await fetch('/speech_to_text', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await response.json();
                    if (data.text) {
                        userInput.value = data.text;
                        sendMessage(); // Optionally send message immediately
                    } else if (data.error) {
                        displayMessage("System", `Speech-to-Text Error: ${data.error}`);
                    }
                } catch (error) {
                    console.error("Error sending audio for transcription:", error);
                    displayMessage("System", "Could not process audio for transcription.");
                }
            };

            mediaRecorder.start();

        } catch (error) {
            console.error("Error accessing microphone:", error);
            voiceInputBtn.classList.remove("recording");
            voiceInputBtn.textContent = "🎤";
            
            // **IMPROVED ERROR HANDLING FOR PERMISSIONS**
            if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
                displayMessage("System", "Microphone access was denied. Please enable it in your browser's site settings and refresh the page.");
            } else if (error.name === 'NotFoundError' || error.name === 'DevicesNotFoundError') {
                displayMessage("System", "No microphone was found. Please ensure a microphone is connected and enabled.");
            } else {
                displayMessage("System", "Could not access microphone. Please ensure permissions are granted and no other app is using it.");
            }
        }
    }
});


// --- Text-to-Speech (AI Response Output) ---
async function speakText(text) {
    try {
        const response = await fetch('/text_to_speech', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        });

        if (response.ok) {
            const audioBlob = await response.blob();
            const audioUrl = URL.createObjectURL(audioBlob);
            ttsAudio.src = audioUrl;
            ttsAudio.play();
            ttsAudio.onended = () => {
                URL.revokeObjectURL(audioUrl); // Clean up the URL
            };
        } else {
            const errorData = await response.json();
            displayMessage("System", `Text-to-Speech Error: ${errorData.error}`);
        }
    } catch (error) {
        console.error("Error with text-to-speech:", error);
        displayMessage("System", "Failed to convert response to speech.");
    }
}

// --- Mode Switching Logic ---
function switchMode(newMode) {
    currentChatMode = newMode;
    if (newMode === 'mental_health') {
        mentalHealthModeBtn.classList.add('active');
        studyBuddyModeBtn.classList.remove('active');
        displayMessage("System", "Switched to Mental Health Assistant mode. How are you feeling today?");
    } else {
        studyBuddyModeBtn.classList.add('active');
        mentalHealthModeBtn.classList.remove('active');
        displayMessage("System", "Switched to AI Study Buddy mode. What would you like to learn about?");
    }
}

mentalHealthModeBtn.addEventListener('click', () => {
    // Clear chat only if the mode is actually changing
    if (currentChatMode !== "mental_health") {
        chatBox.innerHTML = '';
        switchMode("mental_health");
        sendInitialGreeting(); // Start a new conversation
    }
});

studyBuddyModeBtn.addEventListener('click', () => {
    // Clear chat only if the mode is actually changing
    if (currentChatMode !== "study_buddy") {
        chatBox.innerHTML = '';
        switchMode("study_buddy");
        sendInitialGreeting(); // Start a new conversation
    }
});