import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  BackHandler,
  Linking,
  Pressable,
  SafeAreaView,
  StatusBar,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { WebView } from "react-native-webview";

const APP_URL = "https://secondcoach.onrender.com/";
const APP_HOST = "secondcoach.onrender.com";
const INITIAL_LOAD_TIMEOUT_MS = 15000;

export default function App() {
  const webViewRef = useRef(null);
  const [webViewKey, setWebViewKey] = useState(0);
  const [canGoBack, setCanGoBack] = useState(false);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [errorState, setErrorState] = useState(null);

  useEffect(() => {
    if (!isInitialLoading || errorState) {
      return undefined;
    }

    const timeoutId = setTimeout(() => {
      setIsInitialLoading(false);
      setErrorState({
        title: "SecondCoach está tardando más de lo normal.",
        message: "Puede ser un arranque lento o un problema de conexión.",
      });
    }, INITIAL_LOAD_TIMEOUT_MS);

    return () => clearTimeout(timeoutId);
  }, [errorState, isInitialLoading, webViewKey]);

  useEffect(() => {
    const subscription = BackHandler.addEventListener("hardwareBackPress", () => {
      if (canGoBack && webViewRef.current) {
        webViewRef.current.goBack();
        return true;
      }

      return false;
    });

    return () => subscription.remove();
  }, [canGoBack]);

  function handleRetry() {
    setErrorState(null);
    setIsInitialLoading(true);
    setCanGoBack(false);
    setWebViewKey((current) => current + 1);
  }

  function handleLoad() {
    setErrorState(null);
    setIsInitialLoading(false);
  }

  function handleLoadEnd() {
    setIsInitialLoading(false);
  }

  function handleWebError() {
    setIsInitialLoading(false);
    setErrorState({
      title: "No hemos podido abrir SecondCoach.",
      message: "Revisa tu conexión e inténtalo de nuevo.",
    });
  }

  function handleHttpError(event) {
    const statusCode = event?.nativeEvent?.statusCode;
    const statusText = statusCode ? `Error ${statusCode}.` : "La web no ha respondido bien.";

    setIsInitialLoading(false);
    setErrorState({
      title: "No hemos podido cargar SecondCoach.",
      message: statusText,
    });
  }

  function handleNavigationStateChange(navState) {
    setCanGoBack(Boolean(navState?.canGoBack));
  }

  function handleShouldStartLoadWithRequest(request) {
    const url = request?.url || "";
    if (!url) {
      return true;
    }

    if (url.startsWith("mailto:")) {
      Linking.openURL(url).catch(() => {});
      return false;
    }

    try {
      const parsedUrl = new URL(url);
      const isHttp = parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:";

      if (isHttp && parsedUrl.host !== APP_HOST) {
        Linking.openURL(url).catch(() => {});
        return false;
      }
    } catch (_error) {
      return true;
    }

    return true;
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" />
      <WebView
        ref={webViewRef}
        key={webViewKey}
        source={{ uri: APP_URL }}
        javaScriptEnabled={true}
        domStorageEnabled={true}
        originWhitelist={["*"]}
        onLoad={handleLoad}
        onLoadEnd={handleLoadEnd}
        onError={handleWebError}
        onHttpError={handleHttpError}
        onNavigationStateChange={handleNavigationStateChange}
        onShouldStartLoadWithRequest={handleShouldStartLoadWithRequest}
        style={styles.webView}
      />

      {isInitialLoading && !errorState ? (
        <View style={styles.overlay}>
          <ActivityIndicator size="small" color="#111827" />
          <Text style={styles.title}>Cargando SecondCoach…</Text>
        </View>
      ) : null}

      {errorState ? (
        <View style={styles.overlay}>
          <Text style={styles.title}>{errorState.title}</Text>
          <Text style={styles.message}>{errorState.message}</Text>
          <Pressable onPress={handleRetry} style={styles.button}>
            <Text style={styles.buttonText}>Reintentar</Text>
          </Pressable>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#ffffff",
  },
  webView: {
    flex: 1,
  },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#ffffff",
    paddingHorizontal: 28,
  },
  title: {
    marginTop: 14,
    color: "#111827",
    fontSize: 18,
    fontWeight: "600",
    textAlign: "center",
  },
  message: {
    marginTop: 8,
    color: "#6b7280",
    fontSize: 15,
    lineHeight: 22,
    textAlign: "center",
  },
  button: {
    marginTop: 20,
    backgroundColor: "#111827",
    borderRadius: 12,
    paddingHorizontal: 18,
    paddingVertical: 12,
  },
  buttonText: {
    color: "#ffffff",
    fontSize: 15,
    fontWeight: "600",
  },
});
