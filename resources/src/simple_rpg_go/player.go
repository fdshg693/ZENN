// Go equivalent of player.ex.
//
// 各プレイヤーは自分専用の result channel を持ち、サーバーに参加登録時に渡す。
package main

import "fmt"

func JoinPlayer(server chan<- Message, name string) chan Result {
	mailbox := make(chan Result, 1)
	go playerLoop(name, mailbox)
	server <- Message{Kind: MsgJoin, Name: name, PlayerMailbox: mailbox}
	return mailbox
}

func PlayHand(server chan<- Message, name string, hand int) {
	server <- Message{Kind: MsgPlay, Name: name, Hand: hand}
}

func playerLoop(name string, mailbox <-chan Result) {
	result := <-mailbox
	fmt.Printf("[%s] %s\n", name, result.Text)
}
