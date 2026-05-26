#!/bin/bash
g++ -std=c++17 main.cpp imgui*.cpp -o CStage -I. \
  $(pkg-config --cflags --libs opencv4) \
  -lsfml-graphics -lsfml-window -lsfml-system -lsfml-audio \
  -pthread -mwindows -lopengl32