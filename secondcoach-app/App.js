import React from "react";
import { SafeAreaView, StatusBar } from "react-native";
import { WebView } from "react-native-webview";

export default function App() {
  return (
    <SafeAreaView style={{ flex: 1 }}>
      <StatusBar barStyle="dark-content" />
      <WebView
        source={{ uri: "https://secondcoach.onrender.com/start" }}
        startInLoadingState={true}
        javaScriptEnabled={true}
        domStorageEnabled={true}
        originWhitelist={["*"]}
        style={{ flex: 1 }}
      />
    </SafeAreaView>
  );
}