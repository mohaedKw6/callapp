import React, { useState } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createStackNavigator } from '@react-navigation/stack';
import LoginScreen from './screens/LoginScreen';
import FarmScreen from './screens/FarmScreen';
import farmApi from './services/serverApi';
import Colors from './theme/colors';

const Stack = createStackNavigator();

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  const handleLogin = (token, server) => {
    farmApi.setFarmToken(token);
    setIsLoggedIn(true);
  };

  const handleLogout = () => {
    farmApi.setFarmToken(null);
    setIsLoggedIn(false);
  };

  return (
    <NavigationContainer
      theme={{
        dark: true,
        colors: {
          primary: Colors.primary,
          background: Colors.bg,
          card: Colors.bgCard,
          text: Colors.text,
          border: Colors.border,
          notification: Colors.primary,
        },
      }}
    >
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {!isLoggedIn ? (
          <Stack.Screen name="Login">
            {(props) => <LoginScreen {...props} onLogin={handleLogin} />}
          </Stack.Screen>
        ) : (
          <Stack.Screen name="Farm">
            {(props) => <FarmScreen {...props} onLogout={handleLogout} />}
          </Stack.Screen>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
