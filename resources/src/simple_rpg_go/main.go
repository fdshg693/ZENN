// Go equivalent of rps_game.ex.
//
// Elixir の iex 対話セッションに相当する起点。標準入力から手を受け取る。
package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

func startGame() chan<- Message {
	fmt.Println("=== Rock Paper Scissors Game Server Started ===")
	server := StartGameServer()
	fmt.Println("Step 1: JoinPlayer(server, name)")
	fmt.Println("Step 2: playInteractive(server, name)")
	return server
}

func joinAsPlayer(server chan<- Message, name string) chan Result {
	fmt.Printf("=== %s joined the game ===\n", name)
	return JoinPlayer(server, name)
}

func playInteractive(server chan<- Message, name string, reader *bufio.Reader) {
	fmt.Printf("%s's turn! Enter your hand (1=Rock, 2=Paper, 3=Scissors)\n", name)
	hand := getHand(name, reader)
	PlayHand(server, name, hand)
	fmt.Printf("%s has played!\n", name)
}

func getHand(name string, reader *bufio.Reader) int {
	for {
		fmt.Printf("%sの手 (1-3): ", name)
		raw, err := reader.ReadString('\n')
		if err != nil {
			fmt.Println("入力が終了しました")
			return 1
		}
		raw = strings.TrimSpace(raw)
		if n, err := strconv.Atoi(raw); err == nil && n >= 1 && n <= 3 {
			return n
		}
		fmt.Println("1、2、または3を入力してください")
	}
}

func main() {
	reader := bufio.NewReader(os.Stdin)
	server := startGame()
	joinAsPlayer(server, "Alice")
	joinAsPlayer(server, "Bob")
	playInteractive(server, "Alice", reader)
	playInteractive(server, "Bob", reader)
	// 結果の broadcast がプレイヤー goroutine に届くのを少し待つ
	time.Sleep(200 * time.Millisecond)
}
